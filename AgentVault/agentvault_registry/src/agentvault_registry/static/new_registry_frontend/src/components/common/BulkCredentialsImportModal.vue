<template>
  <Teleport to="body">
    <div v-if="show" class="tp-overlay" @click.self="close">
      <div class="tp-modal tp-modal--lg" role="dialog" aria-modal="true" aria-labelledby="bulk-creds-title">
        <!-- Header -->
        <div class="tp-modal-header">
          <span id="bulk-creds-title" class="tp-modal-title">⏶ Bulk Credentials Import</span>
          <button class="tp-modal-close" @click="close" aria-label="Close">✕</button>
        </div>

        <!-- Body -->
        <div class="tp-modal-body">
          <!-- Stage selector pills -->
          <div class="bk-stages">
            <span :class="['bk-stage', stage === 'paste' && 'bk-stage--active']">1 · Paste</span>
            <span class="bk-stage-sep">→</span>
            <span :class="['bk-stage', stage === 'preview' && 'bk-stage--active']">2 · Preview</span>
            <span class="bk-stage-sep">→</span>
            <span :class="['bk-stage', stage === 'apply' && 'bk-stage--active']">3 · Apply</span>
          </div>

          <!-- Stage 1: Paste / file upload -->
          <div v-if="stage === 'paste'">
            <p class="tp-banner tp-banner--info">
              Paste a JSON map of credentials, drag-drop a JSON file, or click below to load a file.
              Three formats accepted:
              <br />• <code>{"did:theprotocol:…": {"client_id": "…", "client_secret": "…", "name": "…"}}</code>
              <br />• <code>[{"did":"…", "client_id":"…", "client_secret":"…"}]</code>
              <br />• <code>{"did":"…", "client_id":"…", "client_secret":"…"}</code> (single)
              <br /><span class="bk-foreign-note">Add <code>"registry_url": "https://op-berlin.op.theprotocol.cloud"</code>
              to an entry to import an agent that lives on ANOTHER registry. It then
              authenticates there, and its calls go there.</span>
            </p>

            <div class="tp-field">
              <label for="bk-textarea" class="tp-label">Credentials JSON</label>
              <textarea
                id="bk-textarea"
                ref="textareaRef"
                v-model="rawJson"
                class="tp-textarea bk-json"
                spellcheck="false"
                placeholder='{"did:theprotocol:…": {"client_id": "agent-…", "client_secret": "tp_secret_…"}}'
                rows="11"
                @drop.prevent="onFileDrop"
                @dragover.prevent
              />
              <p class="tp-hint">Drag one or more <code>.json</code> files onto the textarea, or use the picker below. Several per-registry files are merged into one import.</p>
            </div>

            <div class="bk-actions-row">
              <input
                ref="fileInputRef"
                type="file"
                accept="application/json,.json"
                multiple
                style="display: none"
                data-testid="bulk-file-input"
                @change="onFileSelected"
              />
              <button class="tp-btn tp-btn--ghost" data-testid="bulk-choose-files" @click="fileInputRef?.click()">
                ⇪ Choose JSON file(s)
              </button>
              <button class="tp-btn tp-btn--ghost" @click="rawJson = sampleJson()">
                ⏵ Insert sample
              </button>
              <button class="tp-btn tp-btn--ghost" @click="rawJson = ''" :disabled="!rawJson">
                ⌫ Clear
              </button>
            </div>

            <!-- One line per file, so a batch that partly failed says WHICH file
                 failed instead of reporting a single number that hides it. -->
            <ul v-if="fileReport.length" class="bk-filelist" data-testid="bulk-file-report">
              <li class="bk-filelist-sum">
                <span class="bk-filelist-name">
                  {{ fileSummary.files }} file{{ fileSummary.files === 1 ? '' : 's' }} read<template v-if="fileSummary.failed">, {{ fileSummary.failed }} failed</template>
                </span>
                <span class="bk-filelist-n">{{ mergedCount }}</span>
              </li>
              <!-- Only FAILURES are named. A file that could not be read must never
                   be summarised away: that is the one line the user needs. -->
              <li v-for="(fr, i) in fileSummary.failedRows" :key="i" class="is-bad">
                <span class="bk-filelist-name">{{ fr.name }}</span>
                <span class="bk-filelist-err">{{ fr.error }}</span>
              </li>
              <li v-if="dupNote" class="bk-filelist-dup">
                <span class="bk-filelist-name">{{ dupNote }}</span>
              </li>
            </ul>
            <p v-if="mergedCount" class="tp-hint" data-testid="bulk-merged-count">
              {{ mergedCount }} credential{{ mergedCount === 1 ? '' : 's' }} merged and ready to preview.
            </p>

            <p v-if="parseErr" class="tp-banner tp-banner--danger" role="alert">{{ parseErr }}</p>

            <label class="bk-checkbox">
              <input v-model="verifyEach" type="checkbox" />
              <span>Verify each credential against backend (slower; rejects invalid before saving)</span>
            </label>
            <!-- Verification is ONE request per credential, in sequence, against
                 each credential's own registry. At fleet size that is minutes, so
                 the cost is stated up front rather than discovered as a hang. -->
            <p v-if="verifyEach && verifyCostText" class="tp-hint" data-testid="bulk-verify-cost">
              {{ mergedCount }} credentials will be checked one at a time against their own registries: {{ verifyCostText }}.
            </p>
          </div>

          <!-- Stage 2: Preview parsed entries -->
          <div v-else-if="stage === 'preview'">
            <div class="bk-summary">
              <div class="bk-summary-item">
                <div class="bk-summary-num">{{ parsed.length }}</div>
                <div class="bk-summary-label">Total entries</div>
              </div>
              <div class="bk-summary-item bk-summary-item--ok">
                <div class="bk-summary-num">{{ parsedNew }}</div>
                <div class="bk-summary-label">Will add</div>
              </div>
              <div class="bk-summary-item bk-summary-item--warn">
                <div class="bk-summary-num">{{ parsedOverwrite }}</div>
                <div class="bk-summary-label">Will overwrite</div>
              </div>
              <div class="bk-summary-item bk-summary-item--err">
                <div class="bk-summary-num">{{ parsedInvalid }}</div>
                <div class="bk-summary-label">Invalid (skipped)</div>
              </div>
            </div>

            <div class="bk-preview-list">
              <div v-for="(p, i) in parsed" :key="i" :class="['bk-row', `bk-row--${p.kind}`]">
                <div class="bk-row-icon">
                  <span v-if="p.kind === 'new'">＋</span>
                  <span v-else-if="p.kind === 'overwrite'">↻</span>
                  <span v-else>!</span>
                </div>
                <div class="bk-row-body">
                  <div class="bk-row-name">{{ p.name || 'Unnamed' }}</div>
                  <div class="bk-row-did">{{ p.did }}</div>
                  <div v-if="p.registry_url" class="bk-row-reg">&#8599; {{ p.registry_url }}</div>
                  <div v-if="p.error" class="bk-row-err">{{ p.error }}</div>
                </div>
                <div class="bk-row-tag">{{ p.kind }}</div>
              </div>
            </div>
          </div>

          <!-- Stage 3: Apply -->
          <div v-else-if="stage === 'apply'">
            <div class="bk-progress">
              <div class="bk-progress-bar">
                <div class="bk-progress-fill" :style="{ width: progressPct + '%' }" />
              </div>
              <div class="bk-progress-label">
                {{ progress.done }} / {{ progress.total }} processed
                <span v-if="progress.failed > 0" class="bk-progress-failed">({{ progress.failed }} failed)</span>
                <span v-if="progress.unchecked > 0" class="bk-progress-unchecked" data-testid="bulk-progress-unchecked">({{ progress.unchecked }} not checked)</span>
              </div>
            </div>

            <div v-if="!applying && progress.done === progress.total" class="bk-result">
              <div :class="['tp-banner', progress.failed === 0 && progress.unchecked === 0 ? 'tp-banner--success' : 'tp-banner--warn']" data-testid="bulk-result">
                <strong>Imported {{ progress.done - progress.failed - progress.unchecked }} of {{ progress.total }}</strong>
                <span v-if="progress.failed > 0"> · {{ progress.failed }} failed verification</span>
                <!-- §FESUITE (V0577): a check that got no answer is not a failed verification -->
                <span v-if="progress.unchecked > 0"> · {{ progress.unchecked }} could not be checked (not saved: import them again)</span>
              </div>
            </div>

            <div v-if="applyResults.length" class="bk-preview-list">
              <div v-for="(r, i) in applyResults" :key="i" :class="['bk-row', `bk-row--${r.status}`]">
                <div class="bk-row-icon">
                  <span v-if="r.status === 'ok'">✓</span>
                  <span v-else-if="r.status === 'unchecked'">?</span>
                  <span v-else>✗</span>
                </div>
                <div class="bk-row-body">
                  <div class="bk-row-name">{{ r.name || 'Unnamed' }}</div>
                  <div class="bk-row-did">{{ r.did }}</div>
                  <div v-if="r.error" class="bk-row-err">{{ r.error }}</div>
                </div>
                <div class="bk-row-tag">{{ r.status }}</div>
              </div>
            </div>
          </div>
        </div>

        <!-- Footer -->
        <div class="tp-modal-footer">
          <button class="tp-btn tp-btn--ghost" @click="close" :disabled="applying">
            {{ stage === 'apply' && progress.done === progress.total ? 'Close' : 'Cancel' }}
          </button>

          <button
            v-if="stage === 'paste'"
            class="tp-btn tp-btn--primary"
            :disabled="!rawJson.trim()"
            @click="goPreview"
          >
            Preview →
          </button>

          <button
            v-else-if="stage === 'preview'"
            class="tp-btn tp-btn--ghost"
            @click="stage = 'paste'"
          >
            ← Edit
          </button>
          <button
            v-if="stage === 'preview'"
            class="tp-btn tp-btn--primary"
            :disabled="parsedNew + parsedOverwrite === 0"
            @click="apply"
          >
            Apply ({{ parsedNew + parsedOverwrite }})
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import { ref, watch, nextTick, computed } from 'vue'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import { normalizeEntries, classifyEntries } from '@/services/credImport'
import { agentApi } from '@/services/api/agents'
import { failedForWantOfAnAnswer } from '@/services/api/peerDirect'
import { useUIStore } from '@/stores/ui'
import { useAuthStore } from '@/stores/auth'

interface ParsedEntry {
  did: string
  client_id: string
  client_secret: string
  name?: string
  /**
   * §BRIDGE R11 #12 — which registry this agent lives on.
   *
   * Optional and absent means "this one", so every credential file that worked
   * before still works. When present, the agent authenticates at ITS OWN public
   * address and its agent-scoped calls follow it there — no relay, no new
   * endpoint, no change to any money path (Commander: *"you just trigger the
   * endpoints thru the web address of the registry"*).
   */
  registry_url?: string
  kind: 'new' | 'overwrite' | 'invalid'
  error?: string
}

interface ApplyResult {
  did: string
  name?: string
  /** unchecked: the check got no answer (its registry down, a server error, the browser refusing): not saved, and
   *  never counted as a failed verification ("could not verify is not invalid") */
  status: 'ok' | 'fail' | 'unchecked'
  error?: string
}

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'imported', count: number): void
}>()

const uiStore = useUIStore()
const authStore = useAuthStore()

type Stage = 'paste' | 'preview' | 'apply'
const stage = ref<Stage>('paste')
const rawJson = ref('')
const parseErr = ref('')
const verifyEach = ref(false)
const parsed = ref<ParsedEntry[]>([])
const applying = ref(false)
const applyResults = ref<ApplyResult[]>([])
const progress = ref({ total: 0, done: 0, failed: 0, unchecked: 0 })
const progressPct = computed(() =>
  progress.value.total === 0 ? 0 : Math.round((progress.value.done / progress.value.total) * 100),
)

const textareaRef = ref<HTMLTextAreaElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)

/**
 * §MULTIFILE (2026-08-20) — the cap exists to stop a pathological paste, not a
 * real fleet. The sim roster is 608 credentials across 15 per-registry files,
 * which the old 500 rejected outright with nothing the user could do about it.
 */
const MAX_IMPORT_ENTRIES = 2000
type FileReportRow = { name: string; count: number; error?: string }
const fileReport = ref<FileReportRow[]>([])
const mergedCount = ref(0)
/**
 * The report is SUMMARISED, not listed line by line.
 *
 * A 15-file selection listed per file added ~200px to a modal that is
 * `max-height: 90vh; overflow-y: auto` with the footer INSIDE the scroll, which
 * pushed "Preview →" below the fold at 1600x950 (measured: y=979, viewport 950).
 * A primary action you have to go looking for is a defect, so successes collapse
 * to one line and only FAILURES are named — which is the half you actually need.
 */
const fileSummary = computed(() => {
  const rows = fileReport.value.filter((r) => !r.name.startsWith('%DUP%'))
  const failed = rows.filter((r) => !!r.error)
  return { files: rows.length, failed: failed.length, failedRows: failed }
})
const dupNote = computed(() => fileReport.value.find((r) => r.name.startsWith('%DUP%'))?.name.slice(6) || '')

/** Rough sequential cost of `verifyEach`: one /auth/agent/token per credential. */
const verifyCostText = computed(() => {
  const n = mergedCount.value
  if (!n || n < 50) return ''
  const secs = Math.round(n * 0.3)
  return secs < 90 ? `about ${secs}s` : `about ${Math.round(secs / 60)} min`
})

const parsedNew = computed(() => parsed.value.filter((p) => p.kind === 'new').length)
const parsedOverwrite = computed(() => parsed.value.filter((p) => p.kind === 'overwrite').length)
const parsedInvalid = computed(() => parsed.value.filter((p) => p.kind === 'invalid').length)

watch(
  () => props.show,
  async (v) => {
    if (v) {
      stage.value = 'paste'
      rawJson.value = ''
      parseErr.value = ''
      parsed.value = []
      applying.value = false
      applyResults.value = []
      progress.value = { total: 0, done: 0, failed: 0, unchecked: 0 }
      verifyEach.value = false
      await nextTick()
      textareaRef.value?.focus()
    }
  },
)

function close() {
  if (applying.value) return
  if (stage.value === 'apply' && progress.value.done > 0 && progress.value.done === progress.value.total) {
    emit('imported', progress.value.done - progress.value.failed)
  }
  emit('close')
}

function sampleJson(): string {
  return JSON.stringify(
    {
      'did:theprotocol:00000000-0000-0000-0000-000000000001': {
        client_id: 'agent-1234567890abcdef',
        client_secret: 'tp_secret_abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789',
        name: 'Example Agent A',
      },
      'did:theprotocol:00000000-0000-0000-0000-000000000002': {
        client_id: 'agent-fedcba0987654321',
        client_secret: 'tp_secret_9876543210fedcba9876543210fedcba9876543210fedcba9876543210fedcba',
        name: 'Example Agent B',
      },
    },
    null,
    2,
  )
}

/* normalizeEntries now lives in services/credImport.ts — §POCKETCREDS made it
 * the ONE parsing brain shared with the pocket agent sheet. Same reasoning as
 * before, one level up: a second copy is a place for two surfaces to disagree
 * about which shapes are legal. */

function onFileDrop(ev: DragEvent) {
  const fs = Array.from(ev.dataTransfer?.files || [])
  if (fs.length) void readFiles(fs)
}
function onFileSelected(ev: Event) {
  const el = ev.target as HTMLInputElement
  const fs = Array.from(el.files || [])
  if (fs.length) void readFiles(fs)
  el.value = '' // so the same selection can be re-picked
}

/**
 * §MULTIFILE — read EVERY selected file and merge them into one array.
 *
 * Three things this must not do, each of which a naive version gets wrong:
 *  · it must not concatenate TEXT. Every per-registry file is a top-level
 *    `[...]`, so appending two of them is a syntax error.
 *  · one unreadable or malformed file must not sink the batch. Each file gets
 *    its own line in the report and the rest still merge.
 *  · a DID appearing in two files must not silently produce two rows that both
 *    apply. It is deduped here, last file wins, and the count is REPORTED.
 */
async function readFiles(files: File[]) {
  parseErr.value = ''
  fileReport.value = []
  const merged = new Map<string, any>()
  const keyless: any[] = []
  let dupes = 0

  for (const f of files) {
    let text: string
    try {
      text = await f.text()
    } catch {
      fileReport.value.push({ name: f.name, count: 0, error: 'could not be read' })
      continue
    }
    let doc: any
    try {
      doc = JSON.parse(text)
    } catch (e: any) {
      fileReport.value.push({ name: f.name, count: 0, error: `invalid JSON: ${e.message}` })
      continue
    }
    const entries = normalizeEntries(doc)
    if (!entries) {
      fileReport.value.push({ name: f.name, count: 0, error: 'not a credential object or array' })
      continue
    }
    for (const e of entries) {
      const did = e && typeof e === 'object' ? (e as any).did : undefined
      if (typeof did === 'string' && did) {
        if (merged.has(did)) dupes++
        merged.set(did, e)
      } else {
        keyless.push(e) // kept so goPreview can flag it as invalid, not vanish it
      }
    }
    fileReport.value.push({ name: f.name, count: entries.length })
  }

  const all = [...merged.values(), ...keyless]
  mergedCount.value = all.length
  if (dupes) {
    fileReport.value.push({
      name: `%DUP%${dupes} duplicate DID${dupes === 1 ? '' : 's'} across files (last file wins)`,
      count: 0,
    })
  }
  rawJson.value = all.length ? JSON.stringify(all, null, 2) : ''
  if (!all.length) parseErr.value = 'No credentials found in the selected file(s).'
}

function goPreview() {
  parseErr.value = ''
  let raw: any
  try {
    raw = JSON.parse(rawJson.value)
  } catch (e: any) {
    parseErr.value = `Invalid JSON: ${e.message}`
    return
  }

  // Normalize three accepted shapes into a uniform array.
  const norm = normalizeEntries(raw)
  if (!norm) {
    parseErr.value = 'Top-level must be a JSON object or array of credentials.'
    return
  }
  const entries: any[] = norm

  if (entries.length === 0) {
    parseErr.value = 'No entries found in the JSON.'
    return
  }
  if (entries.length > MAX_IMPORT_ENTRIES) {
    parseErr.value = `Too many entries (${entries.length}). Cap is ${MAX_IMPORT_ENTRIES} per import.`
    return
  }

  const out: ParsedEntry[] = classifyEntries(entries, (d) => agentCredentialsStore.hasCredentials(d))

  parsed.value = out
  stage.value = 'preview'
}

async function apply() {
  applying.value = true
  stage.value = 'apply'
  applyResults.value = []
  const queue = parsed.value.filter((p) => p.kind === 'new' || p.kind === 'overwrite')
  progress.value = { total: queue.length, done: 0, failed: 0, unchecked: 0 }

  // §agentfinder (2026-07-26) — self-ban circuit breaker. Verifying a paste of
  // wrong-registry credentials fires one /auth/agent/token per entry; a long
  // list of 401s trips CrowdSec's http-generic-401-bf and bans the user's own
  // IP (exactly the incident on 2026-07-26 when registry-A creds were imported
  // into frame-C). After MAX_CONSEC_REJECTS consecutive auth rejections we stop
  // verifying the rest and just STORE them (still switchable later, and a real
  // switch surfaces its own error), so a fat-fingered import can never storm
  // the auth endpoint. Store-only entries are never a rejection source.
  const MAX_CONSEC_REJECTS = 5
  let consecRejects = 0
  let verifyDisabled = false

  for (const e of queue) {
    let err: string | undefined
    let unchecked = false

    if (verifyEach.value && !verifyDisabled) {
      try {
        // A foreign credential must be verified AT ITS OWN registry. Checking it
        // here would 401 for the most ordinary reason there is — wrong registry
        // — and five of those trip the self-ban breaker below on credentials
        // that are perfectly good.
        await agentApi.authenticate(e.did,
          { client_id: e.client_id, client_secret: e.client_secret }, e.registry_url)
        consecRejects = 0
      } catch (ex: any) {
        const status = ex?.response?.status
        if (status === 401 || status === 403) {
          consecRejects++
          err = 'Backend rejected credentials'
          if (consecRejects >= MAX_CONSEC_REJECTS) {
            verifyDisabled = true
            uiStore.showWarning(
              'Verification stopped',
              `${consecRejects} credentials in a row were rejected (wrong registry?). ` +
              `Stopped verifying to protect your connection; the rest are being stored ` +
              `without a live check.`,
            )
          }
        } else if (failedForWantOfAnAnswer(ex)) {
          // §FESUITE (V0577): no answer (its registry down, a server error, the browser refusing the request) says
          // nothing about the credential: it was a ✗ "failed verification" here. Not saved, since the person asked for a
          // check before saving; named as not checked. Not counted toward the ban breaker either.
          unchecked = true
        } else {
          // Another refusal (a 4xx other than 401/403) or the console's own error — don't count toward the ban breaker.
          err = ex?.message || 'Verify failed'
        }
      }
    }

    if (unchecked) {
      progress.value = { ...progress.value, done: progress.value.done + 1, unchecked: progress.value.unchecked + 1 }
      applyResults.value.push({
        did: e.did, name: e.name, status: 'unchecked',
        error: 'Could not be checked just now: its registry did not answer. Not saved; import it again.',
      })
      continue
    }

    if (err) {
      progress.value = { ...progress.value, done: progress.value.done + 1, failed: progress.value.failed + 1 }
      applyResults.value.push({ did: e.did, name: e.name, status: 'fail', error: err })
      continue
    }

    try {
      agentCredentialsStore.storeCredentials({
        did: e.did,
        client_id: e.client_id,
        client_secret: e.client_secret,
        name: e.name,
        registry_url: e.registry_url,
      })
      progress.value = { ...progress.value, done: progress.value.done + 1 }
      applyResults.value.push({ did: e.did, name: e.name, status: 'ok' })
    } catch (ex: any) {
      progress.value = { ...progress.value, done: progress.value.done + 1, failed: progress.value.failed + 1 }
      applyResults.value.push({ did: e.did, name: e.name, status: 'fail', error: ex?.message || 'Save failed' })
    }
  }

  applying.value = false
  const ok = progress.value.done - progress.value.failed - progress.value.unchecked
  if (ok > 0) {
    uiStore.showSuccess(
      'Credentials Imported',
      `${ok} agent${ok === 1 ? '' : 's'} now have stored credentials.`,
    )
    // Refresh the available agents list so freshly-credentialed agents become selectable
    try { await authStore.fetchAvailableAgents({ force: true }) } catch { /* non-fatal */ }
  }
  if (progress.value.failed > 0 || progress.value.unchecked > 0) {
    const said: string[] = []
    if (progress.value.failed > 0) said.push(`${progress.value.failed} of ${progress.value.total} entries failed.`)
    if (progress.value.unchecked > 0) {
      said.push(`${progress.value.unchecked} could not be checked (their registry did not answer) and were not saved.`)
    }
    uiStore.showWarning('Partial Import', said.join(' '))
  }
}

// Escape closes this dialog wherever the focus is, the topmost one only (composables/useEscapeClose: an
// @keydown.esc on the overlay heard nothing while the focus stayed on the button that opened it)
useEscapeClose(() => props.show, close)
</script>

<style scoped>
@import '@/components/disputes/tp-disputes-modals.css';

.bk-stages {
  display: flex; align-items: center; gap: 0.5rem;
  margin-bottom: 1rem;
}
.bk-stage {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem; font-weight: 600;
  letter-spacing: 0.1em; text-transform: uppercase;
  color: #7b91b2;
  padding: 0.3rem 0.7rem;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.12);
  border-radius: 9999px;
  background: rgba(255, 255, 255, 0.02);
}
.bk-stage--active {
  color: rgb(0, 210, 210);
  border-color: rgba(var(--nc-primary-rgb), 0.4);
  background: rgba(var(--nc-primary-rgb), 0.08);
}
.bk-stage-sep { color: #7b91b2; font-size: 0.85rem; }

.bk-json {
  font-family: 'IBM Plex Mono', monospace !important;
  font-size: 0.78rem !important;
  min-height: 180px;
}

.bk-actions-row {
  display: flex; flex-wrap: wrap; gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.bk-filelist {
  list-style: none;
  margin: 0.6rem 0 0.4rem;
  padding: 0.4rem 0.6rem;
  border: 1px solid var(--nc-border-subtle, var(--nc-border));
  border-radius: 6px;
  background: var(--nc-deep, var(--nc-surface));
  max-height: 7rem;
  overflow-y: auto;
  font-family: var(--nc-font-mono, monospace);
  font-size: 0.78rem;
}
.bk-filelist li {
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
  padding: 0.15rem 0;
  color: var(--nc-text-secondary);
}
.bk-filelist li.is-bad { color: var(--nc-danger); }
.bk-filelist li.bk-filelist-sum { color: var(--nc-text-primary); }
.bk-filelist li.bk-filelist-dup { color: var(--nc-warning); }
.bk-filelist-name { flex: 1 1 auto; overflow-wrap: anywhere; }
.bk-filelist-n { flex: 0 0 auto; color: var(--nc-text-muted); font-variant-numeric: tabular-nums; }
.bk-filelist-err { flex: 0 0 auto; }

.bk-checkbox {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.82rem;
  color: #c8d6e8;
  margin-top: 0.6rem;
  cursor: pointer;
  user-select: none;
}
.bk-checkbox input[type='checkbox'] {
  width: 16px; height: 16px;
  accent-color: rgb(0, 210, 210);
  cursor: pointer;
}

.bk-summary {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.5rem;
  margin-bottom: 0.85rem;
}
.bk-summary-item {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.1);
  border-radius: 8px;
  padding: 0.6rem 0.75rem;
  text-align: center;
}
.bk-summary-item--ok   { border-color: rgba(34, 197, 94, 0.3); background: rgba(34, 197, 94, 0.06); }
.bk-summary-item--warn { border-color: rgba(251, 191, 36, 0.3); background: rgba(251, 191, 36, 0.06); }
.bk-summary-item--err  { border-color: rgba(239, 68, 68, 0.3); background: rgba(239, 68, 68, 0.06); }
.bk-summary-num   { font-family: 'Orbitron', sans-serif; font-size: 1.4rem; font-weight: 700; color: #e2e8f0; }
.bk-summary-label { font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem; letter-spacing: 0.08em; text-transform: uppercase; color: #6b7e96; margin-top: 0.2rem; }

.bk-preview-list {
  display: flex; flex-direction: column; gap: 0.4rem;
  max-height: 320px; overflow-y: auto;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.08);
  border-radius: 8px;
  padding: 0.4rem;
  background: rgba(255, 255, 255, 0.02);
}
.bk-row {
  display: flex; align-items: flex-start; gap: 0.6rem;
  padding: 0.55rem 0.7rem;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.06);
}
.bk-row--new        { border-color: rgba(34, 197, 94, 0.3); }
.bk-row--overwrite  { border-color: rgba(251, 191, 36, 0.3); }
.bk-row--invalid    { border-color: rgba(239, 68, 68, 0.3); }
.bk-row--ok         { border-color: rgba(34, 197, 94, 0.3); }
.bk-row--fail       { border-color: rgba(239, 68, 68, 0.3); }
.bk-row--unchecked  { border-color: rgba(251, 191, 36, 0.3); }

.bk-row-icon {
  width: 20px; height: 20px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  border-radius: 4px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.85rem; font-weight: 700;
}
.bk-row--new       .bk-row-icon { background: rgba(34, 197, 94, 0.15);   color: rgb(34, 197, 94); }
.bk-row--overwrite .bk-row-icon { background: rgba(251, 191, 36, 0.15);  color: rgb(251, 191, 36); }
.bk-row--invalid   .bk-row-icon { background: rgba(239, 68, 68, 0.15);   color: rgb(239, 68, 68); }
.bk-row--ok        .bk-row-icon { background: rgba(34, 197, 94, 0.15);   color: rgb(34, 197, 94); }
.bk-row--fail      .bk-row-icon { background: rgba(239, 68, 68, 0.15);   color: rgb(239, 68, 68); }
.bk-row--unchecked .bk-row-icon { background: rgba(251, 191, 36, 0.15);  color: rgb(251, 191, 36); }

.bk-row-body { flex: 1; min-width: 0; }
.bk-row-name { font-size: 0.85rem; color: #e2e8f0; font-weight: 600; }
.bk-row-did  { font-family: 'IBM Plex Mono', monospace; font-size: 0.7rem; color: #6b7e96; word-break: break-all; }
.bk-row-err  { font-size: 0.72rem; color: rgb(239, 68, 68); margin-top: 0.2rem; }

.bk-row-tag {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem; letter-spacing: 0.08em; text-transform: uppercase;
  color: #7b91b2;
  align-self: flex-start;
  flex-shrink: 0;
}

.bk-progress { margin-bottom: 1rem; }
.bk-progress-bar {
  width: 100%; height: 8px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 9999px; overflow: hidden;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.1);
}
.bk-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, rgba(var(--nc-primary-rgb), 0.7), rgb(0, 210, 210));
  transition: width 0.2s ease;
}
.bk-progress-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.78rem;
  color: #c8d6e8;
  margin-top: 0.4rem;
}
.bk-progress-failed { color: rgb(239, 68, 68); margin-left: 0.4rem; }
.bk-progress-unchecked { color: rgb(251, 191, 36); margin-left: 0.4rem; }

.bk-result { margin-bottom: 0.85rem; }

code {
  background: rgba(var(--nc-primary-rgb), 0.1);
  border-radius: 3px;
  padding: 1px 5px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.75rem;
  color: rgb(0, 210, 210);
  word-break: break-all;
}
</style>
