<!--
  V0664 C3 (order gwo_4110e12c11a69a93de878829) — TheProtocol Proxy. Public, no sign-in, no request: what the proxy is (bridge a
  system you keep, or migrate off it), how to install it and its first commands, the connector catalog (every source, action and
  sink the SDK ships, each with its fields), and the eight recipes with their blueprints and run commands. Everything on this page
  is generated from the SDK (src/data/proxy/*.generated.json), never written a second time. The contract:
  sessionlogs2026/DESIGN_2026-11-14_PROXY_MIGRATE_CONSOLES.md, C3.
-->
<template>
  <div class="px" data-testid="px-root">
    <ProxyTabs current="proxy" />
    <header class="px-hero">
      <span class="px-badge"><Icon name="mdi:connection" /></span>
      <div>
        <h1>{{ t('proxy.title', 'TheProtocol Proxy') }}</h1>
        <p>{{ t('proxy.subtitle', 'It runs beside a system you keep, reads what that system already writes and turns each record into a call on TheProtocol: an attestation, a milestone\'s evidence, a payment under a mandate. You write one file, proxy.yaml, and no code.') }}</p>
      </div>
    </header>

    <section class="px-paths" :aria-label="t('proxy.pathsAria', 'Bridge or migrate')">
      <article class="px-path" data-testid="px-path-bridge">
        <h2>{{ t('proxy.bridgeTitle', 'Bridge a system that stays') }}</h2>
        <p>{{ t('proxy.bridgeBody', 'The system keeps running as it is. The proxy reads its exports, webhooks, tables, topics or SFTP folders and acts on TheProtocol as its own agent, each record exactly once.') }}</p>
        <RouterLink :to="{ name: 'proxy-new' }" class="px-btn" data-testid="px-to-builder">{{ t('proxy.buildCta', 'Build a spec') }}</RouterLink>
      </article>
      <article class="px-path" data-testid="px-path-migrate">
        <h2>{{ t('proxy.migrateTitle', 'Migrate off it') }}</h2>
        <p>{{ t('proxy.migrateBody', 'Leaving the system instead? The same proxy moves its data: a template, a free dry run on your own machine, a load that runs once and a certificate when both sides agree.') }}</p>
        <RouterLink :to="{ name: 'migrate' }" class="px-btn px-btn-ghost" data-testid="px-to-migrate">{{ t('proxy.migrateCta', 'Migrate a system') }}</RouterLink>
      </article>
    </section>

    <ul class="px-promises" :aria-label="t('proxy.promisesAria', 'What the proxy promises')">
      <li><strong>{{ t('proxy.p1Title', 'Once') }}</strong><span>{{ t('proxy.p1Body', 'A crash, a restart or a repeated delivery never sends a record twice.') }}</span></li>
      <li><strong>{{ t('proxy.p2Title', 'No secret in the file') }}</strong><span>{{ t('proxy.p2Body', 'A credential is named as env:NAME or file:/path; the spec never holds it.') }}</span></li>
      <li><strong>{{ t('proxy.p3Title', 'Least authority') }}</strong><span>{{ t('proxy.p3Body', 'Its agent holds only the permissions its mappings need.') }}</span></li>
    </ul>

    <section class="px-install" data-testid="px-install">
      <h2>{{ t('proxy.installTitle', 'Install and run') }}</h2>
      <p>{{ t('proxy.installBody', 'From PyPI: theprotocol-sdk carries the proxy since 0.8.0. The proxy runs as its own agent: create it in the console and keep its client_id and client_secret where the spec can name them.') }}</p>
      <pre class="px-code" data-testid="px-install-code" tabindex="0" role="region" :aria-label="t('proxy.installAria', 'Install and run: the commands')">{{ INSTALL.join('\n') }}</pre>
      <p class="px-fine">{{ t('proxy.extrasNote', 'A connector that needs a driver has its own extra beside proxy: proxy-mqtt, proxy-sftp, proxy-s3, proxy-quantum, and proxy-sql with proxy-postgresql, proxy-mysql or proxy-sqlserver.') }}</p>
      <p class="px-fine">{{ t('proxy.runNote', 'A dry run maps every record and prints what it would send, sending nothing. --once stops when every source has finished; a receiver (a webhook, MQTT, TheProtocol\'s events) never finishes.') }}</p>
    </section>

    <section class="px-catalog" data-testid="px-catalog">
      <div class="px-section-head">
        <h2>{{ t('proxy.catalogTitle', 'The connectors') }}</h2>
        <span class="px-fine">{{ tp('proxy.catalogFrom', 'From theprotocol-sdk {v}', { v: SDK_VERSION }) }}</span>
      </div>
      <div>
        <div class="px-role-tabs" role="tablist" :aria-label="t('proxy.catalogRolesAria', 'Sources, actions and sinks')">
          <button v-for="r in ROLES" :key="r" type="button" role="tab" class="px-role-tab" :class="{ on: role === r }"
                  :aria-selected="role === r" :data-testid="`px-role-${r}`" @click="role = r">
            {{ roleWord(r) }} <span class="px-count">{{ pluginsOf(r).length }}</span>
          </button>
        </div>
        <p class="px-fine px-role-says">{{ roleSays(role) }}</p>
        <ul class="px-plugins" :data-testid="`px-plugins-${role}`">
          <li v-for="p in pluginsOf(role)" :key="p.name" class="px-plugin" :data-testid="`px-plugin-${role}-${p.name}`">
            <details>
              <summary>
                <code class="px-plugin-name">{{ p.name }}</code>
                <span class="px-plugin-desc">{{ firstLine(p.description) }}</span>
              </summary>
              <table class="px-fields">
                <thead><tr><th>{{ t('proxy.fKey', 'Field') }}</th><th>{{ t('proxy.fType', 'Type') }}</th><th>{{ t('proxy.fWhat', 'What it is') }}</th></tr></thead>
                <tbody>
                  <tr v-for="f in fieldsOf(p.config_schema)" :key="f.key">
                    <td><code>{{ f.key }}</code><span v-if="f.required" class="px-tag">{{ t('proxy.required', 'required') }}</span><span v-if="f.secret" class="px-tag px-tag-secret">{{ t('proxy.secret', 'a reference') }}</span></td>
                    <td class="px-type">{{ f.enumValues ? f.enumValues.join(' · ') : f.type }}</td>
                    <td>{{ f.description || (f.secret ? t('proxy.secretSays', 'A credential, given as env:NAME or file:/path.') : '') }}</td>
                  </tr>
                  <tr v-if="!fieldsOf(p.config_schema).length"><td colspan="3" class="px-fine">{{ t('proxy.noFields', 'No settings.') }}</td></tr>
                </tbody>
              </table>
            </details>
          </li>
        </ul>
      </div>
    </section>

    <section class="px-recipes" data-testid="px-recipes">
      <div class="px-section-head">
        <h2>{{ t('proxy.recipesTitle', 'Eight recipes') }}</h2>
        <a :href="safeExternalUrl(PROXY_RECIPES_URL)" target="_blank" rel="noopener" class="px-fine px-link">{{ t('proxy.recipesRepo', 'The recipes in the repository') }}</a>
      </div>
      <p class="px-fine">{{ t('proxy.recipesBody', 'A ready spec for eight of the blueprints, each with a fake of the system it connects, run end to end on the sandbox before it shipped.') }}</p>
      <ul class="px-recipe-list">
        <li v-for="r in RECIPES" :key="r.id" class="px-recipe" :data-testid="`px-recipe-${r.id}`">
          <header>
            <h3>{{ r.name }}</h3>
            <RouterLink :to="{ name: 'blueprint-detail', params: { id: r.id } }" class="px-link" :data-testid="`px-recipe-bp-${r.id}`">{{ t('proxy.blueprint', 'Its blueprint') }}</RouterLink>
          </header>
          <p class="px-recipe-sum">{{ r.summary }}</p>
          <dl class="px-recipe-table">
            <div><dt>{{ t('proxy.rLegacy', 'The system') }}</dt><dd>{{ r.table.legacy_system }}</dd></div>
            <div><dt>{{ t('proxy.rSource', 'Read from') }}</dt><dd>{{ r.table.source }}</dd></div>
            <div><dt>{{ t('proxy.rOn', 'On TheProtocol') }}</dt><dd>{{ r.table.on_theprotocol }}</dd></div>
            <div v-if="r.table.out"><dt>{{ t('proxy.rOut', 'Out to the system') }}</dt><dd>{{ r.table.out }}</dd></div>
          </dl>
          <details class="px-recipe-more">
            <summary>{{ t('proxy.rHow', 'How it runs') }}</summary>
            <p><strong>{{ t('proxy.rLegacySide', 'The system\'s side.') }}</strong> <template v-for="(part, i) in inline(r.legacy)" :key="i"><code v-if="part.code">{{ part.text }}</code><template v-else>{{ part.text }}</template></template></p>
            <p><strong>{{ t('proxy.rOnSide', 'On TheProtocol.') }}</strong> <template v-for="(part, i) in inline(r.on_theprotocol)" :key="i"><code v-if="part.code">{{ part.text }}</code><template v-else>{{ part.text }}</template></template></p>
            <p><strong>{{ t('proxy.rNeeds', 'What it needs.') }}</strong> <template v-for="(part, i) in inline(r.needs)" :key="i"><code v-if="part.code">{{ part.text }}</code><template v-else>{{ part.text }}</template></template></p>
            <p><strong>{{ t('proxy.rTry', 'Try it locally.') }}</strong> <template v-for="(part, i) in inline(r.try_it)" :key="i"><code v-if="part.code">{{ part.text }}</code><template v-else>{{ part.text }}</template></template></p>
            <pre class="px-code" :data-testid="`px-recipe-cmds-${r.id}`" tabindex="0" role="region" :aria-label="tp('proxy.recipeCmdsAria', '{name}: the commands', { name: r.name })">{{ r.commands.join('\n') }}</pre>
            <p><strong>{{ t('proxy.rCheck', 'Check it.') }}</strong> <template v-for="(part, i) in inline(r.check)" :key="i"><code v-if="part.code">{{ part.text }}</code><template v-else>{{ part.text }}</template></template></p>
          </details>
          <details class="px-recipe-more">
            <summary>{{ t('proxy.rSpec', 'Its spec (proxy.yaml)') }}</summary>
            <pre class="px-code px-code-tall" :data-testid="`px-recipe-yaml-${r.id}`" tabindex="0" role="region" :aria-label="tp('proxy.recipeYamlAria', '{name}: its proxy.yaml', { name: r.name })">{{ r.proxy_yaml }}</pre>
          </details>
        </li>
      </ul>
      <p class="px-fine"><a :href="safeExternalUrl(PROXY_DOCS_URL)" target="_blank" rel="noopener" class="px-link">{{ t('proxy.docsLink', 'The proxy\'s chapter in the docs') }}</a></p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import Icon from '@/components/Icon.vue'
import ProxyTabs from '@/components/proxy/ProxyTabs.vue'
import { useI18n } from '@/composables/useI18n'
import { PROXY_DOCS_URL, PROXY_RECIPES_URL } from '@/data/blueprints/proxy'
import { safeExternalUrl } from '@/utils/safeUrl'
import { RECIPES, ROLES, SDK_VERSION, fieldsOf, pluginsOf, type Role } from '@/services/proxy/spec'
import { inline } from '@/services/proxy/text'

const { t, tp } = useI18n()
const role = ref<Role>('source')

const INSTALL = [
  'pip install "theprotocol-sdk[proxy]"',
  'tp-proxy validate proxy.yaml',
  'tp-proxy run proxy.yaml --dry-run --once   # map and print what it would send, send nothing',
  'tp-proxy run proxy.yaml                    # for real, as a service',
]

function roleWord(r: Role): string {
  return r === 'source' ? t('proxy.sources', 'Sources') : r === 'action' ? t('proxy.actions', 'Actions') : t('proxy.sinks', 'Sinks')
}
function roleSays(r: Role): string {
  if (r === 'source') return t('proxy.sourcesSay', 'Where the proxy reads the system\'s records.')
  if (r === 'action') return t('proxy.actionsSay', 'What it does on TheProtocol with a record, as its own agent.')
  return t('proxy.sinksSay', 'What it hands back to the system: TheProtocol\'s events, as a webhook, a journal, a file.')
}
const firstLine = (s?: string) => (s || '').split('\n')[0]!.replace(/\s+/g, ' ').trim()
</script>

<style scoped>
.px { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); --muted: #8b97a6; --mono: 'IBM Plex Mono', monospace;
  max-width: 72rem; margin: 0 auto; padding: 1.2rem 1.2rem 3rem; color: #e8eaed; display: grid; gap: 1.2rem; font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.px-hero { display: flex; align-items: center; gap: 0.9rem; }
/* on a phone the mark sits above the title, so the paragraph keeps the whole width (pass 2) */
@media (max-width: 600px) { .px-hero { flex-direction: column; align-items: flex-start; gap: 0.6rem; } .px-badge { width: 2.4rem; height: 2.4rem; border-radius: 10px; } }
.px-badge { flex: none; width: 2.8rem; height: 2.8rem; border-radius: 12px; display: grid; place-items: center; background: rgba(var(--cyan-rgb), .1); border: 1px solid rgba(var(--cyan-rgb), .3); }
.px-badge :deep(svg) { width: 1.5rem; height: 1.5rem; color: var(--cyan); }
.px-hero h1 { margin: 0; font-size: 1.8rem; font-weight: 300; letter-spacing: -.01em; }
.px-hero p { margin: 0.3rem 0 0; font-size: 0.9rem; color: var(--muted); max-width: 48rem; line-height: 1.55; }
h2 { margin: 0; font-size: 1.05rem; font-weight: 500; }
.px-paths { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.8rem; }
.px-path, .px-install, .px-recipe { background: linear-gradient(168deg, rgba(255,255,255,.025), rgba(255,255,255,0) 60%), rgba(var(--cyan-rgb), .035); border: 1px solid rgba(var(--cyan-rgb), .16); border-radius: 12px; padding: 1rem 1.1rem; display: grid; gap: 0.55rem; align-content: start; }
.px-path p, .px-install p { margin: 0; font-size: 0.85rem; color: var(--muted); line-height: 1.55; }
.px-btn { justify-self: start; display: inline-flex; align-items: center; min-height: 40px; padding: 0 1rem; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .55); background: rgba(var(--cyan-rgb), .12); color: var(--cyan); font: 600 .8rem var(--mono); text-decoration: none; letter-spacing: .02em; }
.px-btn:hover { background: rgba(var(--cyan-rgb), .2); }
.px-btn:focus-visible, .px-link:focus-visible, .px-role-tab:focus-visible, summary:focus-visible { outline: 2px solid rgba(var(--cyan-rgb), .6); outline-offset: 2px; }
.px-btn-ghost { background: transparent; border-color: rgba(var(--cyan-rgb), .3); }
.px-promises { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.8rem; }
.px-promises li { border-top: 1px solid rgba(var(--cyan-rgb), .25); padding-top: 0.6rem; display: grid; gap: 0.3rem; font-size: 0.84rem; align-content: start; }
.px-promises strong { font: 700 11px/1.2 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--cyan); }
.px-promises span { color: var(--muted); line-height: 1.5; }
.px-code { margin: 0; background: rgba(0,0,0,.4); border: 1px solid rgba(var(--cyan-rgb), .14); border-radius: 8px; padding: 0.7rem 0.9rem; font: 0.78rem/1.6 var(--mono); overflow-x: auto; white-space: pre; color: #dbe4ee; }
.px-code:focus-visible { outline: 2px solid rgba(var(--cyan-rgb), .6); outline-offset: 2px; }
.px-code-tall { max-height: 26rem; overflow-y: auto; }
.px-fine { margin: 0; font-size: 0.78rem; color: var(--muted); line-height: 1.5; }
.px-link { color: var(--cyan); text-decoration: none; border-bottom: 1px solid rgba(var(--cyan-rgb), .35); }
.px-link:hover { border-bottom-color: var(--cyan); }
.px-section-head { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 0.4rem 1rem; }
.px-catalog, .px-recipes { display: grid; gap: 0.7rem; }
.px-role-tabs { display: flex; gap: 0.4rem; flex-wrap: wrap; }
.px-role-tab { min-height: 40px; padding: 0 0.9rem; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .18); background: transparent; color: #cbd5e1; font: 600 .78rem var(--mono); cursor: pointer; display: inline-flex; align-items: center; gap: .45rem; }
.px-role-tab.on { border-color: rgba(var(--cyan-rgb), .6); color: var(--cyan); background: rgba(var(--cyan-rgb), .08); }
.px-count { font-size: .7rem; color: var(--muted); }
.px-role-says { margin-top: 0.5rem; }
.px-plugins { list-style: none; margin: 0.6rem 0 0; padding: 0; display: grid; gap: 0.45rem; }
.px-plugin { border: 1px solid rgba(255,255,255,.07); border-radius: 10px; background: rgba(0,0,0,.18); }
.px-plugin summary { cursor: pointer; padding: 0.7rem 0.9rem; display: flex; flex-wrap: wrap; gap: 0.3rem 0.8rem; align-items: baseline; list-style: none; min-height: 44px; }
.px-plugin summary::-webkit-details-marker { display: none; }
.px-plugin-name { font: 600 .85rem var(--mono); color: var(--cyan); }
.px-plugin-desc { font-size: 0.82rem; color: #aab4c0; line-height: 1.45; flex: 1; min-width: 14rem; }
.px-fields { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
.px-fields th { text-align: left; font: 600 .68rem var(--mono); letter-spacing: .06em; text-transform: uppercase; color: var(--muted); padding: 0.45rem 0.9rem; border-top: 1px solid rgba(255,255,255,.06); }
.px-fields td { padding: 0.45rem 0.9rem; border-top: 1px solid rgba(255,255,255,.04); vertical-align: top; color: #cbd5e1; line-height: 1.45; overflow-wrap: anywhere; }
.px-fields code { font: .78rem var(--mono); color: #e8eaed; }
.px-type { font: .74rem var(--mono); color: var(--muted); white-space: nowrap; }
.px-tag { display: inline-block; margin-left: .4rem; font: 600 .62rem var(--mono); text-transform: uppercase; letter-spacing: .05em; color: var(--muted); border: 1px solid rgba(255,255,255,.12); border-radius: 4px; padding: 1px 4px; vertical-align: 1px; }
.px-tag-secret { color: #fbbf24; border-color: rgba(251,191,36,.35); }
.px-recipe-list { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(min(21rem, 100%), 1fr)); gap: 0.8rem; grid-auto-flow: row dense; }
/* a card holds its own content (its code scrolls inside it); an opened card takes the whole row, so its prose and spec read at full width */
.px-recipe { min-width: 0; }
.px-recipe:has(> details[open]) { grid-column: 1 / -1; }
.px-recipe-more { min-width: 0; }
.px-recipe header .px-link { font: 500 .72rem var(--mono); letter-spacing: .02em; white-space: nowrap; }
.px-recipe header { display: flex; align-items: baseline; justify-content: space-between; gap: 0.6rem; }
.px-recipe h3 { margin: 0; font: 600 .95rem var(--mono); letter-spacing: .06em; color: var(--cyan); }
.px-recipe-sum { margin: 0; font-size: 0.86rem; line-height: 1.45; }
.px-recipe-sum::first-letter { text-transform: uppercase; }
.px-recipe-table { margin: 0; display: grid; gap: 0.25rem; font-size: 0.78rem; }
.px-recipe-table div { display: grid; grid-template-columns: 8.5rem 1fr; gap: 0.6rem; }
.px-recipe-table dt { color: var(--muted); }
.px-recipe-table dd { margin: 0; color: #cbd5e1; }
.px-recipe-more summary { cursor: pointer; font: 600 .74rem var(--mono); color: #cbd5e1; padding: 0.35rem 0; min-height: 36px; display: flex; align-items: center; gap: 0.5rem; list-style: none; }
.px-recipe-more summary::-webkit-details-marker { display: none; }
.px-recipe-more summary::before { content: ''; flex: none; width: 0.4rem; height: 0.4rem; border-right: 1.5px solid currentColor; border-bottom: 1.5px solid currentColor; transform: rotate(-45deg); transition: transform .15s ease; }
.px-recipe-more[open] > summary::before { transform: rotate(45deg); }
.px-recipe-more summary:hover { color: var(--cyan); }
.px-recipe-more + .px-recipe-more { border-top: 1px solid rgba(255,255,255,.06); }
.px-recipe-more p { margin: 0.45rem 0 0; font-size: 0.8rem; color: #aab4c0; line-height: 1.55; }
.px-recipe-more p strong { color: #e8eaed; font-weight: 500; }
.px-recipe-more code { font: .76rem var(--mono); color: #e8eaed; background: rgba(255,255,255,.05); border-radius: 3px; padding: 0 3px; }
.px-recipe-more .px-code { margin-top: 0.5rem; }
@media (max-width: 720px) {
  .px { padding: 1rem .8rem 2.5rem; }
  .px-paths, .px-promises { grid-template-columns: 1fr; }
  .px-hero h1 { font-size: 1.5rem; }
  .px-recipe-list { grid-template-columns: 1fr; }
  .px-recipe-table div { grid-template-columns: 7rem 1fr; }
}
</style>
