<!--
  V0666 (gwo_dc5050837e93b0a64d1fdae7, room seq 4404: "pypi update on landing"): the SDK's install line with the
  version the console's catalog was made from (it moves with each release: never a literal here), PyPI and the docs' proxy
  chapter. The version is read after the page is up (composables/useSdkVersion), so the landing's first load does not
  carry the catalog.
-->
<template>
  <div class="lsd" data-testid="lp-sdk-line">
    <code class="lsd-cmd" data-testid="lp-sdk-pip">pip install theprotocol-sdk</code>
    <div class="lsd-links">
      <a :href="safeExternalUrl(PYPI_URL)" target="_blank" rel="noopener" class="lsd-link" data-testid="lp-sdk-pypi">
        {{ t('landingPage.sdk.onPypi', 'On PyPI') }} <span v-if="sdkVersion" class="lsd-ver" data-testid="lp-sdk-version">v{{ sdkVersion }}</span>
      </a>
      <span class="lsd-sep" aria-hidden="true">·</span>
      <a :href="safeExternalUrl(PROXY_DOCS_URL)" target="_blank" rel="noopener" class="lsd-link" data-testid="lp-sdk-docs">{{ t('landingPage.sdk.proxyChapter', 'The proxy chapter') }}</a>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { PROXY_DOCS_URL } from '@/data/blueprints/proxy'
import { useSdkVersion } from '@/composables/useSdkVersion'
import { useI18n } from '@/composables/useI18n'
import { safeExternalUrl } from '@/utils/safeUrl'

const PYPI_URL = 'https://pypi.org/project/theprotocol-sdk/'
const { t } = useI18n()
const { sdkVersion, load } = useSdkVersion()
onMounted(() => { void load() })
</script>

<style scoped>
.lsd { display: flex; flex-direction: column; align-items: center; gap: 0.7rem; margin: 2rem 0; }
.lsd-cmd { display: inline-block; padding: 0.6rem 1.5rem; border-radius: 6px; background: rgba(0, 0, 0, 0.4); border: 1px solid rgba(245, 180, 30, 0.15);
  font-family: 'IBM Plex Mono', monospace; font-size: 0.85rem; color: rgba(245, 180, 30, 0.85); letter-spacing: 0.03em; max-width: 100%; overflow-wrap: anywhere; }
.lsd-links { display: flex; flex-wrap: wrap; justify-content: center; align-items: center; gap: 0.3rem 0.7rem; font-family: 'IBM Plex Mono', monospace; font-size: 0.7rem; }
.lsd-link { display: inline-flex; align-items: center; gap: 0.45rem; min-height: 32px; color: rgba(var(--nc-primary-rgb), 0.85); text-decoration: none; border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.25); }
.lsd-link:hover { border-bottom-color: rgba(var(--nc-primary-rgb), 0.7); }
.lsd-link:focus-visible { outline: 2px solid rgba(var(--nc-primary-rgb), 0.6); outline-offset: 3px; }
.lsd-ver { padding: 1px 6px; border-radius: 3px; border: 1px solid rgba(var(--nc-primary-rgb), 0.25); font-size: 0.62rem; color: rgba(var(--nc-primary-rgb), 0.75); }
.lsd-sep { color: rgba(255, 255, 255, 0.25); }
</style>
