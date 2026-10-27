<script setup lang="ts">
/**
 * §LEGALKIT (Terms § 10.2): after a material change the platform asks for renewed acceptance at the next login.
 * Shown when /developers/me says `tos_reconsent_required`; "Later" dismisses it for this browser session and
 * nothing is blocked (the Terms let a person continue under the old version until a feature needs the new one).
 * Accepting posts to /api/v1/legal/accept with the version the registry serves; a stale version is refused
 * with the current one, and the modal reloads the profile either way.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/composables/useI18n'
import { apiClient } from '@/services/api/client'
import { useLegalConfig } from '@/services/legal/config'

const auth = useAuthStore()
const { t, tp } = useI18n()
const { config: legal } = useLegalConfig()

const DISMISS_KEY = 'legal.reconsent.dismissed'
const dismissed = ref(false)
const busy = ref(false)
const error = ref('')

function readDismissed(): boolean {
  try { return sessionStorage.getItem(DISMISS_KEY) === (auth.user?.tos_current_version || '') } catch { return false }
}
function writeDismissed(): void {
  try { sessionStorage.setItem(DISMISS_KEY, auth.user?.tos_current_version || '') } catch { /* private window */ }
}

onMounted(() => { dismissed.value = readDismissed() })
watch(() => auth.user?.tos_current_version, () => { dismissed.value = readDismissed() })

const version = computed(() => auth.user?.tos_current_version || legal.value?.tos_version || '')
const effective = computed(() => legal.value?.effective_label || legal.value?.effective || '')
// V0414: the registry names the documents to accept; a profile from an older registry names none, so the Terms alone
// are asked when it says `tos_reconsent_required` (the behaviour every console had before).
const KNOWN: Record<string, { slug: string; label: string; fallback: string }> = {
  terms: { slug: 'terms', label: 'legalReconsent.documents.terms', fallback: 'Terms of Service' },
  operators: { slug: 'operators', label: 'legalReconsent.documents.operators', fallback: 'Federation Operator Terms' },
}
const documents = computed<string[]>(() => {
  const named = (auth.user?.reconsent_documents || []).filter((d) => d in KNOWN)
  if (named.length) return named
  return auth.user?.tos_reconsent_required ? ['terms'] : []
})
function versionOf(doc: string): string {
  if (doc === 'terms') return version.value
  const v = (legal.value as any)?.documents?.[doc]
  return typeof v === 'string' && v ? v : version.value
}
const show = computed(() => Boolean(auth.isAuthenticated && documents.value.length > 0 && !dismissed.value && version.value))

async function accept(): Promise<void> {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    for (const doc of documents.value) {
      await apiClient.post('/legal/accept', { document: doc, version: versionOf(doc) })
    }
    await auth.refreshProfile()
  } catch (e: any) {
    // a 409 names the version now served; reload the profile so the modal asks for that one
    if (e?.response?.status === 409) { await auth.refreshProfile(); busy.value = false; return }
    error.value = t('legalReconsent.error', 'Your acceptance could not be recorded. Reload the page and try again.')
  } finally {
    busy.value = false
  }
}
function later(): void {
  writeDismissed()
  dismissed.value = true
}
</script>

<template>
  <Teleport to="body">
    <div v-if="show" class="lrc-backdrop" role="dialog" aria-modal="true" aria-labelledby="lrc-title" data-testid="legal-reconsent">
      <div class="lrc-card">
        <h2 id="lrc-title" class="lrc-title">{{ t('legalReconsent.title', 'The Terms of Service have changed') }}</h2>
        <!-- §FESUITE (2026-10-09): the date comes from the legal config; while that read has not answered, the sentence
             says no date rather than "applies from ." (sweeps/recovery on V0587, 39 admin pages) -->
        <p class="lrc-body" data-testid="legal-reconsent-body">{{ effective
          ? tp('legalReconsent.body', 'A new version of the Terms ({version}) applies from {effective}. Please read what changed and accept the new version; you can also decide later.', { version, effective })
          : tp('legalReconsent.bodyNoDate', 'A new version of the Terms ({version}) applies. Please read what changed and accept the new version to keep using every feature; you can also decide later.', { version }) }}</p>
        <ul class="lrc-docs" data-testid="legal-reconsent-documents">
          <li v-for="doc in documents" :key="doc">
            <a :href="`#/legal/${KNOWN[doc].slug}`" target="_blank" rel="noopener noreferrer">{{ t(KNOWN[doc].label, KNOWN[doc].fallback) }}</a>
            <span class="lrc-doc-version">v{{ versionOf(doc) }}</span>
          </li>
        </ul>
        <p class="lrc-links">
          <a href="#/legal/changes" target="_blank" rel="noopener noreferrer">{{ t('legalReconsent.changes', 'What changed') }}</a>
        </p>
        <p v-if="error" class="lrc-error">{{ error }}</p>
        <div class="lrc-actions">
          <button class="nc-btn nc-btn-secondary" type="button" data-testid="legal-reconsent-later" @click="later">{{ t('legalReconsent.later', 'Later') }}</button>
          <button class="nc-btn nc-btn-primary" type="button" :disabled="busy" data-testid="legal-reconsent-accept" @click="accept">{{ tp('legalReconsent.accept', 'I accept version {version}', { version }) }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.lrc-backdrop { position: fixed; inset: 0; z-index: 10080; display: flex; align-items: center; justify-content: center; padding: 16px; background: rgba(4, 8, 14, 0.72); backdrop-filter: none; }
.lrc-card { width: min(560px, 100%); background: var(--nc-surface, #0c1118); color: var(--nc-text, #e6edf3); border: 1px solid var(--nc-border, #22303f); border-radius: 12px; padding: 22px 22px 18px; box-shadow: 0 24px 60px rgba(0,0,0,.5); }
.lrc-title { margin: 0 0 10px; font-size: 1.15rem; }
.lrc-body { margin: 0 0 12px; line-height: 1.5; font-size: 0.95rem; }
.lrc-links { display: flex; gap: 16px; margin: 0 0 12px; font-size: 0.92rem; }
.lrc-links a { text-decoration: underline; }
.lrc-error { color: var(--nc-danger, #ff6b6b); font-size: 0.9rem; margin: 0 0 10px; }
.lrc-actions { display: flex; justify-content: flex-end; gap: 10px; flex-wrap: wrap; }
.lrc-docs { list-style: none; margin: 0.6rem 0; padding: 0; display: flex; flex-direction: column; gap: 0.35rem; }
.lrc-docs a { font-weight: 600; }
.lrc-doc-version { margin-left: 0.5rem; opacity: 0.7; font-size: 0.85em; }
</style>
