<template>
  <Teleport to="body">
    <div v-if="show" class="gvm-overlay" @click.self="$emit('close')">
      <div class="gvm-panel" role="dialog" aria-modal="true" aria-label="Credentials vault">
        <header class="gvm-head">
          <h3 class="gvm-title"><Icon name="mdi:shield-lock" :size="14" /> Credentials vault</h3>
          <button class="gvm-x" type="button" aria-label="Close" @click="$emit('close')"><Icon name="mdi:close" :size="14" /></button>
        </header>

        <div class="gvm-tabs">
          <button class="gvm-tab" :class="{ 'gvm-tab--on': tab === 'import' }" type="button" @click="tab = 'import'">Import</button>
          <button class="gvm-tab" :class="{ 'gvm-tab--on': tab === 'export' }" type="button" @click="tab = 'export'">Export</button>
        </div>

        <div v-if="tab === 'import'" class="gvm-body">
          <label class="gvm-check">
            <input v-model="sameForAll" type="checkbox" />
            The same developer account on every registry of this federation ({{ peerCount }})
          </label>
          <template v-if="sameForAll">
            <input v-model.trim="allEmail" class="gvm-input" type="email" autocomplete="username" placeholder="developer email" />
            <input v-model="allPassword" class="gvm-input" type="password" autocomplete="current-password" placeholder="password (used once per registry, never stored)" />
          </template>

          <label class="gvm-label">Credentials <span class="gvm-opt">(a saved vault, a credentials download, a list of agent credentials, or lines of <code>key&#9;url&#9;email&#9;password</code>; <code>#</code> comments ignored)</span></label>
          <textarea v-model="vaultText" class="gvm-input gvm-ta" rows="6" spellcheck="false" data-testid="gvm-text"
                    placeholder='{"version":2,"registries":[…],"agents":[…]}&#10;&#10;…or:&#10;asia&#9;https://asia.theprotocol.cloud&#9;you@example.com&#9;password'></textarea>
          <input ref="fileInput" type="file" accept="application/json,.json,.txt,.tsv" class="gvm-file" @change="onFile" />

          <p v-if="parsed.format !== 'unreadable' && vaultText.trim()" class="gvm-note" data-testid="gvm-summary">
            {{ parsed.developers.length }} registry sign-in{{ parsed.developers.length === 1 ? '' : 's' }} ·
            {{ parsed.entries.length }} agent credential{{ parsed.entries.length === 1 ? '' : 's' }}
          </p>
          <p v-else-if="vaultText.trim()" class="gvm-err-line">{{ parsed.errors[0] }}</p>

          <label v-if="homeless > 0" class="gvm-label" data-testid="gvm-home-question">
            {{ homeless }} credential{{ homeless === 1 ? '' : 's' }} in this file name no registry. Which registry do they belong to?
            <select v-model="homelessHome" class="gvm-input">
              <option v-for="o in homeOptions" :key="o.key" :value="o.key">{{ o.label }}</option>
            </select>
          </label>

          <button class="gvm-go" type="button" data-testid="gvm-go"
                  :disabled="busy || (!vaultText.trim() && !(sameForAll && allEmail && allPassword))" @click="runImport">
            {{ busy ? `Importing… (${progress})` : 'Import & connect' }}
          </button>

          <ul v-if="report.length" class="gvm-report" data-testid="gvm-report">
            <li v-for="r in report" :key="r.key" class="gvm-report-row" :class="r.ok ? 'gvm-ok' : 'gvm-err'">
              <span class="gvm-report-k">{{ r.key }}</span>
              <span class="gvm-report-d">{{ r.detail }}</span>
            </li>
          </ul>
        </div>

        <div v-else class="gvm-body">
          <label class="gvm-check"><input v-model="includeSecrets" type="checkbox" /> Include agent client secrets in the export</label>
          <p class="gvm-note">Exports your saved agent credentials (each with the registry it belongs to) and the registries you are
            signed in to. Passwords are never stored, so they are never exported. The file imports here as it is.</p>
          <button class="gvm-go" type="button" data-testid="gvm-export" @click="runExport">Download theprotocol-vault.json</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
// §FEFRAME W3 (V0504) — the ONE import: every credential file this console ever produced (services/credImport.ts),
// into the ONE vault (services/agentCredentialsStore.ts) and the session hub (stores/sessions.ts).
// Registry sign-ins go DIRECTLY to each registry of the frame manifest (no "relay-available" gate: the relay refused
// every non-admin, so a vault import connected nothing for most people). Agent credentials land in the vault with
// their home resolved against the manifest (a key, a URL, a by-registry group); rows that name no home get ONE
// question per file; a registry this federation does not name is reported, never guessed. The export is the
// importer's own shape (vault v2).
import { computed, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { useSessionHub } from '@/stores/sessions'
import { useFrameManifest } from '@/composables/useFrameManifest'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import { classifyEntries, exportVaultV2, parseCredentialText, type HomeAnswer, type ImportDocument } from '@/services/credImport'
import { entryByOrigin } from '@/services/frameManifest'
import { homeForKey } from '@/services/commandRoster'
import type { RegistryDirectory } from '@/services/api/command'

const props = defineProps<{ show: boolean; directory?: RegistryDirectory | null }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'imported', summary: string): void }>()

const hub = useSessionHub()
const fm = useFrameManifest()
const tab = ref<'import' | 'export'>('import')
const vaultText = ref('')
const sameForAll = ref(false)
const allEmail = ref('')
const allPassword = ref('')
const includeSecrets = ref(false)
const busy = ref(false)
const progress = ref('')
const report = ref<Array<{ key: string; ok: boolean; detail: string }>>([])
const fileInput = ref<HTMLInputElement | null>(null)

const peerCount = computed(() => fm.peers.value.length)
const parsed = computed(() => parseCredentialText(vaultText.value))
const homeless = computed(() => parsed.value.entries.filter(e => e && !e.registry_url && !e.registry_key).length)
const homeOptions = computed(() => {
  const self = fm.self.value
  const opts = self ? [{ key: self.key, label: `${self.display_name} (this registry)` }] : []
  return opts.concat(fm.peers.value.map(e => ({ key: e.key, label: `${e.display_name}${e.role === 'operator' ? ' (operator)' : ''}` })))
})
const homelessHome = ref<string>('')

function onFile(ev: Event) {
  const f = (ev.target as HTMLInputElement).files?.[0]
  if (!f) return
  const r = new FileReader()
  r.onload = () => { vaultText.value = String(r.result || '') }
  r.readAsText(f)
}

/** A registry key or URL from a file, against the manifest. */
function resolveRegistry(key: string | null, url: string | null): { key: string; url: string | null; label: string } | null {
  const m = fm.manifest.value
  if (!m) return null
  if (url) {
    let origin: string | null = null
    try { origin = new URL(url).origin } catch { origin = null }
    const e = origin ? entryByOrigin(m, origin) : null
    if (e) return { key: e.key, url: e.key === m.self.key ? null : (e.public_url || e.console_url), label: e.display_name }
  }
  if (key) {
    const h = homeForKey(key, m)
    if (h) {
      const k = h.url === null ? m.self.key : key.toLowerCase()
      const e = fm.byKey(k)
      return { key: e?.key || k, url: h.url, label: e?.display_name || key }
    }
  }
  return null
}

const resolveHome = (registryKey: string): HomeAnswer => {
  const r = resolveRegistry(registryKey, null)
  return r ? { ok: true, url: r.url } : { ok: false, reason: `"${registryKey}" is not a registry of this federation (retired or unknown)` }
}

async function runImport() {
  busy.value = true
  report.value = []
  const empty: ImportDocument = { format: 'entries', entries: [], developers: [], errors: [] }
  const doc: ImportDocument = vaultText.value.trim() ? parsed.value : empty
  if (vaultText.value.trim() && doc.format === 'unreadable') {
    report.value.push({ key: 'file', ok: false, detail: doc.errors[0] || 'unreadable' })
    busy.value = false
    return
  }
  const selfKey = fm.self.value?.key || null

  // 1. registry sign-ins: the file's, plus the same account everywhere when asked
  const signIns: Array<{ key: string | null; url: string | null; email: string; password?: string }> =
    doc.developers.map(d => ({ key: d.registry_key, url: d.registry_url, email: d.email, password: d.password }))
  if (sameForAll.value && allEmail.value && allPassword.value) {
    for (const e of fm.peers.value) {
      if (!signIns.some(s => (s.key || '').toLowerCase() === e.key)) signIns.push({ key: e.key, url: e.public_url, email: allEmail.value, password: allPassword.value })
    }
  }
  let connected = 0
  for (let i = 0; i < signIns.length; i++) {
    const s = signIns[i]
    progress.value = `${i + 1}/${signIns.length}`
    const r = resolveRegistry(s.key, s.url)
    const label = r?.label || s.key || s.url || 'registry'
    if (!r) { report.value.push({ key: label, ok: false, detail: 'not a registry of this federation (retired or unknown): nothing sent' }); continue }
    if (r.key === selfKey || r.url === null) { report.value.push({ key: label, ok: true, detail: 'this registry: you are signed in here' }); continue }
    if (!s.password) { report.value.push({ key: label, ok: true, detail: `listed for ${s.email}: sign in to it from the console (passwords are never stored)` }); continue }
    const ok = await hub.connectAdmin(r.key, s.email, s.password, r.url)
    if (ok) connected++
    report.value.push({ key: label, ok, detail: ok ? `signed in directly as ${s.email}` : (hub.sessionFor(r.key).error || 'sign-in failed') })
  }

  // 2. agent credentials: into the one vault, each with its home
  const chosen = homelessHome.value || selfKey || ''
  const entries = doc.entries.map(e => (e && !e.registry_url && !e.registry_key && chosen ? { ...e, registry_key: chosen } : e))
  const rows = classifyEntries(entries, d => agentCredentialsStore.hasCredentials(d), resolveHome)
  let stored = 0
  for (const r of rows) {
    if (r.kind === 'invalid') { report.value.push({ key: r.did, ok: false, detail: r.error || 'invalid' }); continue }
    const home = r.registry_url ? resolveRegistry(null, r.registry_url) : null
    agentCredentialsStore.storeCredentials({
      did: r.did, client_id: r.client_id, client_secret: r.client_secret, name: r.name,
      registry_url: r.registry_url || undefined,
      registry: home && home.url ? home.key : undefined,
    })
    stored++
  }
  if (stored) report.value.push({ key: 'agents', ok: true, detail: `${stored} agent credential${stored === 1 ? '' : 's'} saved to your vault` })

  allPassword.value = ''
  busy.value = false
  progress.value = ''
  emit('imported', `${connected} registr${connected === 1 ? 'y' : 'ies'} connected · ${stored} agent credential${stored === 1 ? '' : 's'} saved`)
}

function runExport() {
  const rows = Object.values(agentCredentialsStore.getAllCredentials())
  const m = fm.manifest.value
  const registries = (m ? [m.self, ...m.peers] : []).map(e => ({
    key: e.key, name: e.display_name, url: e.public_url || e.console_url,
    email: hub.isConnected(e.key) ? hub.sessionFor(e.key).adminEmail : null,
  }))
  const v = exportVaultV2(rows, registries, includeSecrets.value)
  const blob = new Blob([JSON.stringify(v, null, 2)], { type: 'application/json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = 'theprotocol-vault.json'
  a.click()
  URL.revokeObjectURL(a.href)
}

// Escape closes this dialog wherever the focus is, the topmost one only (composables/useEscapeClose: an
// @keydown.esc on the overlay heard nothing while the focus stayed on the button that opened it)
useEscapeClose(() => props.show, () => emit('close'))
</script>

<style scoped>
.gvm-overlay {
  position: fixed; inset: 0; z-index: 10300;
  background: rgba(2, 5, 10, 0.72);
  backdrop-filter: blur(3px); -webkit-backdrop-filter: blur(3px);
  display: flex; align-items: center; justify-content: center; padding: 18px;
}
.gvm-panel {
  width: 100%; max-width: 560px; max-height: 86vh; overflow-y: auto;
  background: linear-gradient(168deg, rgba(255,255,255,.025), transparent 60%), rgba(13, 18, 28, 0.97);
  border: 1px solid rgba(var(--nc-primary-rgb, 0,210,210), 0.22);
  border-radius: 12px; color: var(--nc-text-primary, #e8eaed);
  box-shadow: 0 18px 60px rgba(0,0,0,.55);
}
.gvm-head { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px 8px; }
.gvm-title { margin: 0; display: inline-flex; align-items: center; gap: 7px; font-size: .95rem; font-weight: 700; }
.gvm-x { width: 30px; height: 30px; display: grid; place-items: center; background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.08); border-radius: 7px; color: var(--nc-text-muted, #94a3b8); cursor: pointer; }
.gvm-tabs { display: flex; gap: 6px; padding: 0 16px 10px; }
.gvm-tab { padding: 5px 13px; border-radius: 7px; font-size: .72rem; font-weight: 700; cursor: pointer; background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.1); color: var(--nc-text-muted, #94a3b8); }
.gvm-tab--on { color: var(--nc-primary, #00d2d2); border-color: rgba(var(--nc-primary-rgb, 0,210,210), .45); background: rgba(var(--nc-primary-rgb, 0,210,210), .1); }
.gvm-body { padding: 4px 16px 16px; display: grid; gap: 9px; }
.gvm-check { display: flex; align-items: center; gap: 8px; font-size: .76rem; cursor: pointer; }
.gvm-label { font-size: .64rem; text-transform: uppercase; letter-spacing: .1em; font-weight: 700; color: var(--nc-text-muted, #94a3b8); }
.gvm-opt { text-transform: none; letter-spacing: 0; font-weight: 500; }
.gvm-input {
  width: 100%; padding: 8px 11px;
  background: rgba(4, 8, 14, 0.55); border: 1px solid rgba(255,255,255,.1); border-radius: 8px;
  color: var(--nc-text-primary, #e8eaed); font-size: 16px;
}
.gvm-input:focus { outline: none; border-color: rgba(var(--nc-primary-rgb, 0,210,210), .55); }
.gvm-ta { font-family: ui-monospace, monospace; font-size: .72rem; resize: vertical; }
.gvm-file { font-size: .72rem; color: var(--nc-text-muted, #94a3b8); }
.gvm-go {
  min-height: 38px; padding: 0 16px; border-radius: 8px; cursor: pointer; font-size: .8rem; font-weight: 700;
  background: rgba(var(--nc-primary-rgb, 0,210,210), .14);
  border: 1px solid rgba(var(--nc-primary-rgb, 0,210,210), .45);
  color: var(--nc-primary, #00d2d2);
}
.gvm-go:disabled { opacity: .45; cursor: not-allowed; }
.gvm-err-line { margin: 0; font-size: .7rem; color: #ef4444; }
.gvm-note { margin: 0; font-size: .7rem; color: var(--nc-text-muted, #94a3b8); }
.gvm-report { list-style: none; margin: 4px 0 0; padding: 0; display: grid; gap: 4px; max-height: 200px; overflow-y: auto; }
.gvm-report-row { display: flex; gap: 9px; font-size: .7rem; padding: 5px 8px; border-radius: 6px; background: rgba(255,255,255,.025); border: 1px solid rgba(255,255,255,.05); }
.gvm-report-k { font-weight: 800; min-width: 92px; }
.gvm-ok .gvm-report-k { color: #10b981; }
.gvm-err .gvm-report-k { color: #ef4444; }
.gvm-report-d { color: var(--nc-text-muted, #94a3b8); }
@media (max-width: 640px) {
  .gvm-overlay { align-items: flex-end; padding: 0; }
  .gvm-panel { max-width: none; border-radius: 14px 14px 0 0; }
}
</style>
