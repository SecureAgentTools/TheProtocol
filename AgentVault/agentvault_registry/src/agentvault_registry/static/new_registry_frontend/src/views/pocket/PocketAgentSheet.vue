<!-- POCKET · Agent sheet — §POCKETCREDS (2026-08-23). The ONE door for
     "who am I acting as" and "how do credentials get onto this phone".
     Three lanes:
       SWITCH — pick the acting agent from the device's credential vault
                (global: every pocket surface reads the same store).
       IMPORT — paste or attach the same three JSON shapes the desktop bulk
                importer takes; the parsing brain is services/credImport.ts,
                shared with the desktop modal, deliberately not a copy.
       ADOPT  — make this phone self-sufficient with NO credential transport:
                for an agent you own, the registry's existing password-gated
                reset rail mints FRESH credentials that land straight in the
                vault. The secret is never rendered anywhere; the old secret
                dies, and the sheet says so before asking for a password.
     Money never moves here; this sheet only changes who CAN move it. -->
<template>
  <transition name="pk-sheet">
    <div v-if="open" class="ags-scrim" @click.self="close">
      <div ref="trapEl" class="ags-sheet" role="dialog" aria-modal="true" data-testid="pk-agsheet"
           :aria-label="t('pocket.agentSheet.title', 'Acting agent')">
        <div class="ags-grip" aria-hidden="true"></div>
        <h2 class="ags-title"><Icon name="mdi:robot" /> {{ t('pocket.agentSheet.title', 'Acting agent') }}
          <button class="ags-x" :aria-label="t('pocket.agentSheet.close', 'Close')" @click="close">&times;</button>
        </h2>

        <div class="ags-tabs" role="tablist">
          <button class="ags-tab" :class="{ on: tab === 'switch' }" role="tab" :aria-selected="tab === 'switch'"
                  data-testid="ag-tab-switch" @click="tab = 'switch'">{{ t('pocket.agentSheet.tabSwitch', 'Switch') }}</button>
          <button class="ags-tab" :class="{ on: tab === 'import' }" role="tab" :aria-selected="tab === 'import'"
                  data-testid="ag-tab-import" @click="tab = 'import'">{{ t('pocket.agentSheet.tabImport', 'Import') }}</button>
          <button class="ags-tab" :class="{ on: tab === 'adopt' }" role="tab" :aria-selected="tab === 'adopt'"
                  data-testid="ag-tab-adopt" @click="tab = 'adopt'">{{ t('pocket.agentSheet.tabAdopt', 'Adopt') }}</button>
        </div>

        <!-- ── SWITCH ─────────────────────────────────────────────── -->
        <div v-if="tab === 'switch'" class="ags-body">
          <AgentSwitchList data-testid="ag-list" @switched="onListSwitched" @create="emit('create')" />
        </div>

        <!-- ── IMPORT ─────────────────────────────────────────────── -->
        <div v-else-if="tab === 'import'" class="ags-body">
          <template v-if="impStage === 'paste'">
            <p class="ags-note">{{ t('pocket.agentSheet.importIntro', 'Paste exported credential JSON, or attach the files. Same three shapes as the desktop importer.') }}</p>
            <textarea v-model="impRaw" class="ags-ta" data-testid="ag-import-text" rows="6"
                      :placeholder="t('pocket.agentSheet.importPastePh', 'Paste credential JSON here')"></textarea>
            <div class="ags-btnrow">
              <button class="ags-mini" @click="fileInput?.click()">
                <Icon name="mdi:import" /> {{ t('pocket.agentSheet.importFiles', 'Attach JSON files') }}
              </button>
              <input ref="fileInput" type="file" accept=".json,application/json" multiple class="ags-hidden"
                     data-testid="ag-import-files" @change="onFiles" />
              <button class="ags-btn" :disabled="!impRaw.trim()" data-testid="ag-import-preview" @click="goPreview">
                {{ t('pocket.agentSheet.importPreview', 'Preview') }}
              </button>
            </div>
            <p v-for="row in impFileReport" :key="row.name" class="ags-note" :class="{ 'ags-warn': !!row.error }">
              {{ row.name }}: {{ row.error || tp('pocket.agentSheet.importFileOk', '{n} entries', { n: row.count }) }}
            </p>
            <p v-if="impDupNote" class="ags-note">{{ impDupNote }}</p>
            <p v-if="impErr" class="ags-note ags-warn" data-testid="ag-import-err">{{ impErr }}</p>
          </template>

          <template v-else-if="impStage === 'preview'">
            <div class="ags-sumrow" data-testid="ag-import-summary">
              <span class="ags-sum ags-sum-new">{{ tp('pocket.agentSheet.importNew', '{n} new', { n: impNew }) }}</span>
              <span class="ags-sum">{{ tp('pocket.agentSheet.importOverwrite', '{n} replace', { n: impOverwrite }) }}</span>
              <span class="ags-sum ags-sum-bad">{{ tp('pocket.agentSheet.importInvalid', '{n} invalid', { n: impInvalid }) }}</span>
            </div>
            <p v-for="(bad, i) in impInvalidRows.slice(0, 4)" :key="i" class="ags-note ags-warn">{{ shorten(bad.did) }}: {{ bad.error }}</p>
            <p v-if="impInvalidRows.length > 4" class="ags-note ags-warn">{{ tp('pocket.agentSheet.importMoreInvalid', '+{n} more invalid entries', { n: impInvalidRows.length - 4 }) }}</p>
            <div class="ags-btnrow">
              <button class="ags-mini" @click="impStage = 'paste'">{{ t('pocket.agentSheet.back', 'Back') }}</button>
              <button class="ags-btn" :disabled="impNew + impOverwrite === 0" data-testid="ag-import-apply" @click="applyImport">
                {{ tp('pocket.agentSheet.importApply', 'Store {n} on this device', { n: impNew + impOverwrite }) }}
              </button>
            </div>
            <p class="ags-note">{{ t('pocket.agentSheet.importNoVerify', 'Stored without contacting any registry. A wrong credential shows itself at first use — nothing is fired at auth endpoints from a paste.') }}</p>
          </template>

          <template v-else>
            <p class="ags-done" data-testid="ag-import-done"><Icon name="mdi:check-circle" />
              {{ tp('pocket.agentSheet.importDone', '{n} credentials stored on this device.', { n: impApplied }) }}</p>
            <p v-if="vaultPlain" class="ags-note ags-warn">{{ t('pocket.agentSheet.sealHint', 'They are unencrypted right now. More → Seal agent credentials puts them behind your fingerprint.') }}</p>
            <button class="ags-btn" @click="tab = 'switch'">{{ t('pocket.agentSheet.goSwitch', 'Pick the acting agent') }}</button>
          </template>
        </div>

        <!-- ── ADOPT ──────────────────────────────────────────────── -->
        <div v-else class="ags-body">
          <template v-if="adStage === 'search'">
            <p class="ags-note">{{ t('pocket.agentSheet.adoptIntro', 'Adopt an agent you own onto this phone: the registry issues fresh credentials straight into the vault. Nothing is copied from another device, and the secret is never shown.') }}</p>
            <input v-model="adQ" class="ags-in" type="search" data-testid="ag-adopt-q"
                   :placeholder="t('pocket.agentSheet.adoptSearchPh', 'Search your fleet by name or DID')"
                   @input="debouncedAdSearch" />
            <p v-if="adBusy" class="ags-note">{{ t('pocket.agentSheet.searching', 'Searching…') }}</p>
            <p v-else-if="adErr" class="ags-note ags-warn" data-testid="ag-adopt-err">{{ adErr }}</p>
            <p v-else-if="adSearched && !adRows.length" class="ags-note">{{ t('pocket.agentSheet.adoptNone', 'No agent of yours matches that.') }}</p>
            <ul v-else class="ags-list">
              <li v-for="row in adRows" :key="row.did">
                <button class="ags-row" data-testid="ag-adopt-row" @click="pickAdopt(row)">
                  <span class="ags-row-main">
                    <span class="ags-row-name">{{ row.name || row.human_readable_id || shorten(row.did) }}</span>
                    <span class="ags-row-sub">{{ shorten(row.did) }} · {{ fmtBal(row.liquid_balance) }}</span>
                  </span>
                  <span v-if="hasCreds(row.did)" class="ags-chip">{{ t('pocket.agentSheet.alreadyHere', 'on this device') }}</span>
                </button>
              </li>
            </ul>
          </template>

          <template v-else-if="adStage === 'confirm'">
            <p class="ags-adopt-name">{{ adPick?.name || shorten(adPick?.did || '') }}</p>
            <div class="ags-warnbox" data-testid="ag-adopt-warn">
              <p><strong>{{ t('pocket.agentSheet.adoptWarnTitle', 'This issues new credentials.') }}</strong></p>
              <p>{{ t('pocket.agentSheet.adoptWarn1', 'The old secret stops working the moment this succeeds. Anything still running with it — a deployed service, another device that was not sealed — loses access to this agent.') }}</p>
              <p>{{ t('pocket.agentSheet.adoptWarn2', 'The new secret goes directly into this device’s vault and is never displayed. The registry allows 3 resets per hour.') }}</p>
            </div>
            <label class="ags-ack"><input v-model="adAck" type="checkbox" data-testid="ag-adopt-ack" />
              {{ t('pocket.agentSheet.adoptAck', 'I understand the old secret dies now') }}</label>
            <input v-model="adPw" class="ags-in" type="password" autocomplete="current-password" data-testid="ag-adopt-pw"
                   :disabled="!adAck" :placeholder="t('pocket.agentSheet.adoptPw', 'Account password (the rail demands it)')" />
            <div class="ags-btnrow">
              <button class="ags-mini" :disabled="adBusy" @click="adStage = 'search'; adErr = ''">{{ t('pocket.agentSheet.back', 'Back') }}</button>
              <button class="ags-btn" :disabled="!adAck || adPw.length < 8 || adBusy" data-testid="ag-adopt-go" @click="doAdopt">
                {{ adBusy ? t('pocket.agentSheet.adoptBusy', 'Issuing…') : t('pocket.agentSheet.adoptGo', 'Adopt onto this phone') }}
              </button>
            </div>
            <p v-if="adErr" class="ags-note ags-warn" data-testid="ag-adopt-err">{{ adErr }}</p>
          </template>

          <template v-else>
            <p class="ags-done" data-testid="ag-adopt-done"><Icon name="mdi:check-circle" />
              {{ t('pocket.agentSheet.adoptDone', 'Adopted. Fresh credentials are in the vault; the secret was never shown.') }}</p>
            <p v-if="adWarnSrv" class="ags-note">{{ adWarnSrv }}</p>
            <p v-if="vaultPlain" class="ags-note ags-warn">{{ t('pocket.agentSheet.sealHint', 'They are unencrypted right now. More → Seal agent credentials puts them behind your fingerprint.') }}</p>
            <button class="ags-btn" data-testid="ag-adopt-switch" @click="switchToAdopted">
              {{ t('pocket.agentSheet.adoptSwitchNow', 'Act as it now') }}</button>
          </template>
        </div>
      </div>
    </div>
  </transition>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, computed, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import AgentSwitchList from '@/components/pocket/AgentSwitchList.vue'
import { useFocusTrap } from '@/composables/useFocusTrap'
import { usePocketAgent } from '@/composables/usePocketAgent'
import { useAuthStore } from '@/stores/auth'
import { apiClient } from '@/services/api/client'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import { credentialVault } from '@/services/credentialVault'
import { normalizeEntries, classifyEntries, mergeCredDocs, MAX_IMPORT_ENTRIES, type ParsedCredEntry } from '@/services/credImport'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{ open: boolean; initialTab?: 'switch' | 'import' | 'adopt' }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'switched', did: string): void; (e: 'create'): void }>()
const { t, tp } = useI18n()
const auth = useAuthStore()
const { credAgents, noAgentReason, ensureAgentFor } = usePocketAgent()

const trapEl = ref<HTMLElement | null>(null)
useFocusTrap(trapEl, { activeWhen: computed(() => props.open) })

const tab = ref<'switch' | 'import' | 'adopt'>('switch')
function close() { emit('close') }

const activeDid = computed<string>(() => (auth as any).activeAgent?.did || '')
const shorten = (d: string) => (d && d.length > 26 ? `${d.slice(0, 16)}…${d.slice(-6)}` : d)
// `hostname`, never `host`: host CARRIES THE PORT and broke matching before (§V0189).
function hostLabel(u?: string): string {
  if (!u) return t('pocket.agentSheet.thisRegistry', 'this registry')
  try { return new URL(u).hostname } catch { return u }
}

/* ── SWITCH ── */
const q = ref('')
const switching = ref(false)
const switchMsg = ref('')

/** The shared list performs the switch itself; this sheet only has to close and
 *  tell its parent, exactly as its own doSwitch did. */
function onListSwitched(did: string) { emit('switched', did); close() }
const filtered = computed(() => {
  const needle = q.value.trim().toLowerCase()
  if (!needle) return credAgents.value
  return credAgents.value.filter(a =>
    (a.name || '').toLowerCase().includes(needle)
    || a.did.toLowerCase().includes(needle)
    || (a.registry_url || '').toLowerCase().includes(needle))
})
async function doSwitch(did: string) {
  switchMsg.value = ''; switching.value = true
  try {
    const ok = await ensureAgentFor(did)
    if (ok) {
      try { localStorage.setItem('activeAgentId', did) } catch { /* choice lives for this session anyway */ }
      emit('switched', did)
      close()
    } else {
      switchMsg.value = t('pocket.agentSheet.switchFailed', 'Could not sign in as that agent — its credential may be stale or belong to an unreachable registry.')
    }
  } finally { switching.value = false }
}

/* ── IMPORT — parsing brain shared with the desktop modal ── */
const impStage = ref<'paste' | 'preview' | 'done'>('paste')
const impRaw = ref('')
const impErr = ref('')
const impFileReport = ref<{ name: string; count: number; error?: string }[]>([])
const impDupNote = ref('')
const impParsed = ref<ParsedCredEntry[]>([])
const impApplied = ref(0)
const fileInput = ref<HTMLInputElement | null>(null)
const impNew = computed(() => impParsed.value.filter(p => p.kind === 'new').length)
const impOverwrite = computed(() => impParsed.value.filter(p => p.kind === 'overwrite').length)
const impInvalid = computed(() => impParsed.value.filter(p => p.kind === 'invalid').length)
const impInvalidRows = computed(() => impParsed.value.filter(p => p.kind === 'invalid'))
const vaultPlain = computed(() => { try { return credentialVault.state() === 'plain' } catch { return false } })

async function onFiles(ev: Event) {
  impErr.value = ''; impDupNote.value = ''
  const el = ev.target as HTMLInputElement
  const files = Array.from(el.files || [])
  el.value = ''
  if (!files.length) return
  const docs: { name: string; text: string }[] = []
  for (const f of files) {
    try { docs.push({ name: f.name, text: await f.text() }) }
    catch { impFileReport.value.push({ name: f.name, count: 0, error: t('pocket.agentSheet.fileUnreadable', 'could not be read') }) }
  }
  const { entries, report, dupes } = mergeCredDocs(docs)
  impFileReport.value = report
  if (dupes) impDupNote.value = tp('pocket.agentSheet.importDupes', '{n} duplicate DIDs across files (last file wins)', { n: dupes })
  impRaw.value = entries.length ? JSON.stringify(entries, null, 2) : ''
  if (!entries.length) impErr.value = t('pocket.agentSheet.importEmptyFiles', 'No credentials found in the selected files.')
}
function goPreview() {
  impErr.value = ''
  let raw: any
  try { raw = JSON.parse(impRaw.value) } catch (e: any) { impErr.value = `Invalid JSON: ${e?.message || 'parse error'}`; return }
  const entries = normalizeEntries(raw)
  if (!entries) { impErr.value = t('pocket.agentSheet.importBadShape', 'Top-level must be a JSON object or array of credentials.'); return }
  if (!entries.length) { impErr.value = t('pocket.agentSheet.importEmpty', 'No entries found in the JSON.'); return }
  if (entries.length > MAX_IMPORT_ENTRIES) { impErr.value = tp('pocket.agentSheet.importTooMany', 'Too many entries ({n}). Cap is {max} per import.', { n: entries.length, max: MAX_IMPORT_ENTRIES }); return }
  impParsed.value = classifyEntries(entries, (d) => agentCredentialsStore.hasCredentials(d))
  impStage.value = 'preview'
}
function applyImport() {
  const good = impParsed.value.filter(p => p.kind === 'new' || p.kind === 'overwrite')
  agentCredentialsStore.storeMultipleCredentials(good.map(p => ({
    did: p.did, client_id: p.client_id, client_secret: p.client_secret,
    name: p.name, registry_url: p.registry_url,
  })))
  impApplied.value = good.length
  impStage.value = 'done'
}

/* ── ADOPT — the no-transport lane ── */
interface AdoptRow { did: string; name?: string; human_readable_id?: string; liquid_balance?: string; status?: string }
const adStage = ref<'search' | 'confirm' | 'done'>('search')
const adQ = ref('')
const adRows = ref<AdoptRow[]>([])
const adBusy = ref(false)
const adSearched = ref(false)
const adErr = ref('')
const adPick = ref<AdoptRow | null>(null)
const adAck = ref(false)
const adPw = ref('')
const adWarnSrv = ref('')
let adTimer: ReturnType<typeof setTimeout> | null = null
function debouncedAdSearch() { if (adTimer) clearTimeout(adTimer); adTimer = setTimeout(() => { void adSearch() }, 350) }
async function adSearch() {
  const needle = adQ.value.trim()
  adErr.value = ''
  if (needle.length < 2) { adRows.value = []; adSearched.value = false; return }
  adBusy.value = true
  try {
    const { data } = await apiClient.get('/developers/me/agents', { params: { q: needle, limit: 20 } })
    adRows.value = (Array.isArray(data) ? data : []).filter((r: any) => r?.did && r.status !== 'revoked')
    adSearched.value = true
  } catch (e: any) {
    adErr.value = e?.response?.data?.detail || e?.message || t('pocket.agentSheet.adoptSearchFailed', 'Fleet search failed.')
  } finally { adBusy.value = false }
}
const hasCreds = (did: string) => { try { return agentCredentialsStore.hasCredentials(did) } catch { return false } }
function fmtBal(b?: string): string {
  const n = Number(b)
  return Number.isFinite(n) ? n.toLocaleString(appLocale(), { maximumFractionDigits: 2 }) : '—'
}
function pickAdopt(row: AdoptRow) { adPick.value = row; adAck.value = false; adPw.value = ''; adErr.value = ''; adStage.value = 'confirm' }
async function doAdopt() {
  if (!adPick.value) return
  adErr.value = ''; adBusy.value = true
  try {
    // The rail's own three layers: dev JWT + ownership + this password. The
    // response's client_secret is handled HERE only — stored, never rendered.
    const { data } = await apiClient.post(
      `/onboard/agents/${encodeURIComponent(adPick.value.did)}/reset-credentials`,
      { password: adPw.value },
    )
    agentCredentialsStore.storeCredentials({
      did: data.agent_did || adPick.value.did,
      client_id: data.client_id,
      client_secret: data.client_secret,
      name: adPick.value.name || adPick.value.human_readable_id,
    })
    adWarnSrv.value = typeof data?.warning === 'string' ? data.warning : ''
    adStage.value = 'done'
  } catch (e: any) {
    const st = e?.response?.status
    adErr.value = st === 429
      ? t('pocket.agentSheet.adoptRate', 'Rate limit: the registry allows 3 credential resets per hour. Try again later.')
      : (e?.response?.data?.detail || e?.message || t('pocket.agentSheet.adoptFailed', 'Adoption failed — nothing was changed.'))
  } finally {
    adPw.value = '' // the password never outlives the attempt
    adBusy.value = false
  }
}
async function switchToAdopted() {
  const did = adPick.value?.did
  if (did) await doSwitch(did)
}

/* Escape closes — the PocketSend pattern: a WINDOW listener while open,
 * because @keydown.esc on a non-focusable overlay never fires (§BRIDGE R11).
 * Guarded during the two in-flight moments so a nervous Escape cannot orphan
 * a rotation that is already on the wire. */
function onEscKey(e: KeyboardEvent) { if (e.key === 'Escape' && props.open && !adBusy.value && !switching.value) close() }

/* A deep link naming a lane while the sheet is ALREADY open must still land
 * on it — the open-watcher alone misses that (the §POCKETBRIDGE5 watcher-
 * never-fires-for-already-true class, met again here in its own battery). */
watch(() => props.initialTab, (v) => { if (props.open && v) tab.value = v })

/* Reset per open; honor the requested lane. */
watch(() => props.open, (o) => {
  if (o) window.addEventListener('keydown', onEscKey)
  else window.removeEventListener('keydown', onEscKey)
  if (!o) return
  tab.value = props.initialTab || 'switch'
  q.value = ''; switchMsg.value = ''
  impStage.value = 'paste'; impRaw.value = ''; impErr.value = ''; impFileReport.value = []; impDupNote.value = ''; impParsed.value = []
  adStage.value = 'search'; adQ.value = ''; adRows.value = []; adSearched.value = false; adErr.value = ''; adPick.value = null; adAck.value = false; adPw.value = ''
}, { immediate: true })
</script>

<style scoped>
.ags-scrim { position: fixed; inset: 0; z-index: 90; background: rgba(2,4,8,0.6); backdrop-filter: blur(2px);
  display: flex; align-items: flex-end; justify-content: center; }
.ags-sheet { width: 100%; max-width: 560px; max-height: 88dvh; overflow-y: auto; -webkit-overflow-scrolling: touch;
  background: #0c0f15; border: 1px solid rgba(255,255,255,0.09); border-bottom: none; border-radius: 22px 22px 0 0;
  padding: 0.5rem 1rem calc(1rem + env(safe-area-inset-bottom, 0px)); box-sizing: border-box; }
.ags-grip { width: 38px; height: 4px; border-radius: 2px; background: rgba(255,255,255,0.18); margin: 0.25rem auto 0.6rem; }
.ags-title { display: flex; align-items: center; gap: 0.5rem; font-size: 0.95rem; margin: 0 0 0.6rem; }
.ags-title :deep(svg) { width: 1.1rem; height: 1.1rem; color: var(--nc-primary, #00d4ff); }
.ags-x { margin-left: auto; background: none; border: none; color: rgba(230,237,243,0.6); font-size: 1.4rem;
  min-width: 44px; min-height: 44px; cursor: pointer; -webkit-tap-highlight-color: transparent; }
.ags-tabs { display: flex; gap: 0.4rem; margin-bottom: 0.7rem; }
.ags-tab { flex: 1 1 0; min-height: 44px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.1);
  background: rgba(255,255,255,0.04); color: rgba(230,237,243,0.7); font-size: 0.8rem; font-weight: 600; cursor: pointer;
  -webkit-tap-highlight-color: transparent; }
.ags-tab.on { color: var(--nc-primary, #00d4ff); border-color: rgba(0,212,255,0.35); background: rgba(0,212,255,0.08); }
.ags-body { display: flex; flex-direction: column; gap: 0.55rem; }
.ags-in { width: 100%; box-sizing: border-box; min-height: 44px; font-size: 16px; color: inherit;
  background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.12); border-radius: 12px; padding: 0.55rem 0.7rem; }
.ags-ta { width: 100%; box-sizing: border-box; font-size: 16px; font-family: ui-monospace, monospace; color: inherit;
  background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.12); border-radius: 12px; padding: 0.55rem 0.7rem; resize: vertical; }
.ags-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.4rem; }
.ags-row { display: flex; align-items: center; gap: 0.6rem; width: 100%; text-align: left; min-height: 52px;
  background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px;
  color: inherit; padding: 0.55rem 0.75rem; cursor: pointer; -webkit-tap-highlight-color: transparent; }
.ags-row:active { background: rgba(255,255,255,0.08); }
.ags-row.active { border-color: rgba(0,212,255,0.4); background: rgba(0,212,255,0.07); }
.ags-row-main { display: flex; flex-direction: column; gap: 0.12rem; min-width: 0; flex: 1 1 auto; }
.ags-row-name { font-size: 0.86rem; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ags-row-sub { font-size: 0.7rem; opacity: 0.55; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ags-check { color: #34d399; flex: 0 0 auto; }
.ags-check :deep(svg) { width: 1.15rem; height: 1.15rem; }
.ags-chip { flex: 0 0 auto; font-size: 0.62rem; font-weight: 700; letter-spacing: 0.05em; color: #34d399;
  background: rgba(16,185,129,0.12); border: 1px solid rgba(16,185,129,0.3); border-radius: 7px; padding: 0.2rem 0.45rem; }
.ags-note { font-size: 0.75rem; opacity: 0.7; margin: 0; }
.ags-warn { color: #ffb38a; opacity: 0.95; }
.ags-btnrow { display: flex; gap: 0.5rem; align-items: center; }
.ags-btn { flex: 1 1 auto; min-height: 48px; border-radius: 13px; border: 1px solid rgba(0,212,255,0.35);
  background: linear-gradient(160deg, rgba(0,212,255,0.18), rgba(0,212,255,0.06)); color: #e6edf3;
  font-size: 0.86rem; font-weight: 600; cursor: pointer; -webkit-tap-highlight-color: transparent; }
.ags-btn:disabled { opacity: 0.45; cursor: default; }
.ags-mini { flex: 0 0 auto; display: inline-flex; align-items: center; gap: 0.4rem; min-height: 48px; border-radius: 13px;
  border: 1px solid rgba(255,255,255,0.12); background: rgba(255,255,255,0.04); color: #e6edf3;
  font-size: 0.8rem; padding: 0 0.8rem; cursor: pointer; -webkit-tap-highlight-color: transparent; }
.ags-mini :deep(svg) { width: 1rem; height: 1rem; }
.ags-hidden { display: none; }
.ags-sumrow { display: flex; gap: 0.45rem; }
.ags-sum { font-size: 0.72rem; font-weight: 700; border-radius: 8px; padding: 0.3rem 0.55rem;
  background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); }
.ags-sum-new { color: #34d399; border-color: rgba(16,185,129,0.35); background: rgba(16,185,129,0.1); }
.ags-sum-bad { color: #ff8a8a; border-color: rgba(255,107,107,0.35); background: rgba(255,107,107,0.08); }
.ags-done { display: flex; align-items: center; gap: 0.5rem; font-size: 0.88rem; font-weight: 600; color: #34d399; margin: 0; }
.ags-done :deep(svg) { width: 1.2rem; height: 1.2rem; }
.ags-adopt-name { font-size: 0.95rem; font-weight: 700; margin: 0; }
.ags-warnbox { border: 1px solid rgba(224,166,63,0.4); background: rgba(224,166,63,0.08); border-radius: 12px;
  padding: 0.65rem 0.8rem; display: flex; flex-direction: column; gap: 0.4rem; }
.ags-warnbox p { margin: 0; font-size: 0.76rem; line-height: 1.45; color: #ffd9a0; }
.ags-ack { display: flex; align-items: center; gap: 0.55rem; font-size: 0.8rem; min-height: 44px; cursor: pointer; }
.ags-ack input { width: 1.15rem; height: 1.15rem; }
.pk-sheet-enter-active, .pk-sheet-leave-active { transition: opacity 0.2s ease; }
.pk-sheet-enter-active .ags-sheet, .pk-sheet-leave-active .ags-sheet { transition: transform 0.24s cubic-bezier(0.34,1.3,0.64,1); }
.pk-sheet-enter-from, .pk-sheet-leave-to { opacity: 0; }
.pk-sheet-enter-from .ags-sheet, .pk-sheet-leave-to .ags-sheet { transform: translateY(24px); }
@media (prefers-reduced-motion: reduce) {
  .pk-sheet-enter-active, .pk-sheet-leave-active, .pk-sheet-enter-active .ags-sheet, .pk-sheet-leave-active .ags-sheet { transition: none; }
}
</style>
