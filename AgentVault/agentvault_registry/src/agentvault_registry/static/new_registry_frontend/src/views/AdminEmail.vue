<template>
  <!-- Build #10 (2026-05-07): Email Pipeline Admin.
       Renders the existing /admin/email/preview/* endpoints in a side-by-side
       template browser. No new backend — pure frontend on top of the email
       preview pipeline that ships with the registry. -->
  <div class="ae">
    <div class="ae-ambient">
      <div class="ae-grid"></div>
      <div class="ae-glow ae-glow-1"></div>
      <div class="ae-glow ae-glow-2"></div>
    </div>

    <section class="ae-hero">
      <div class="ae-hero-inner">
        <div class="ae-chip"><span class="ae-chip-dot"></span>{{ t('adminEmailView.hero.chip') }}</div>
        <h1 class="ae-h1">{{ t('adminEmailView.hero.h1a') }}<span class="ae-accent">{{ t('adminEmailView.hero.h1Accent') }}</span></h1>
        <p class="ae-lead">{{ t('adminEmailView.hero.lead') }}</p>
      </div>
    </section>

    <div class="ae-body">
      <div v-if="loading && !list" class="ae-center">
        <div class="ae-spinner"></div>
        <p class="ae-loading-text">{{ t('adminEmailView.loading') }}</p>
      </div>

      <div v-else-if="error && !list" class="ae-center">
        <p class="ae-error-text"><Icon name="mdi:alert" /> {{ error }}</p>
        <button class="ae-btn ae-btn--ghost" @click="loadList">{{ t('adminEmailView.error.retry') }}</button>
      </div>

      <template v-else-if="list">
        <div class="ae-layout">
          <!-- Sidebar: template list -->
          <aside class="ae-sidebar">
            <div class="ae-side-section">
              <div class="ae-side-title">{{ t('adminEmailView.sidebar.templatesTitle') }} <span class="ae-side-count">({{ list.templates.length }})</span></div>
              <input
                v-model="search"
                type="text"
                :placeholder="t('adminEmailView.search')"
                class="ae-side-search"
              />
              <div class="ae-side-list">
                <button
                  v-for="tpl in filteredTemplates" :key="tpl"
                  class="ae-side-item"
                  :class="{ 'ae-side-item--active': activeTemplate === tpl }"
                  @click="selectTemplate(tpl)"
                  :title="tpl"
                >
                  <span class="ae-side-item-glyph"><Icon name="mdi:email-outline" /></span>
                  <span class="ae-side-item-label">{{ tpl }}</span>
                </button>
              </div>
            </div>

            <div class="ae-side-section">
              <div class="ae-side-title">{{ t('adminEmailView.sidebar.themeTitle') }}</div>
              <div class="ae-side-help">{{ t('adminEmailView.sidebar.themeHelp') }}</div>
              <div class="ae-theme-switch">
                <button
                  class="ae-theme-btn ae-theme-btn--neural"
                  :class="{ 'ae-theme-btn--active': theme === 'neural' }"
                  @click="setTheme('neural')"
                >
                  <span class="ae-theme-dot ae-theme-dot--neural"></span>{{ t('adminEmailView.sidebar.themeNeural') }}
                </button>
                <button
                  class="ae-theme-btn ae-theme-btn--sovereign"
                  :class="{ 'ae-theme-btn--active': theme === 'sovereign' }"
                  @click="setTheme('sovereign')"
                >
                  <span class="ae-theme-dot ae-theme-dot--sovereign"></span>{{ t('adminEmailView.sidebar.themeSovereign') }}
                </button>
              </div>
            </div>

            <div class="ae-side-section">
              <div class="ae-side-title">{{ t('adminEmailView.sidebar.formatTitle') }}</div>
              <div class="ae-format-switch">
                <button
                  class="ae-format-btn"
                  :class="{ 'ae-format-btn--active': format === 'html' }"
                  @click="setFormat('html')"
                >{{ t('adminEmailView.sidebar.formatHtml') }}</button>
                <button
                  class="ae-format-btn"
                  :class="{ 'ae-format-btn--active': format === 'text' }"
                  @click="setFormat('text')"
                >{{ t('adminEmailView.sidebar.formatText') }}</button>
              </div>
            </div>

            <div class="ae-side-section">
              <div class="ae-side-title">{{ t('adminEmailView.sidebar.actionsTitle') }}</div>
              <button class="ae-btn ae-btn--ghost ae-btn--full" @click="copyHtml" :disabled="!previewBody">⎘ {{ t('adminEmailView.sidebar.copy') }} {{ format.toUpperCase() }}</button>
              <button class="ae-btn ae-btn--ghost ae-btn--full" @click="downloadHtml" :disabled="!previewBody">⤓ {{ t('adminEmailView.sidebar.download') }}</button>
            </div>

            <!-- §2026-07-29 — SEND panel: pick recipients + which identity it goes out as. -->
            <div class="ae-side-section ae-send-section">
              <div class="ae-side-title">SEND</div>
              <div class="ae-side-help">Compose a real email from this template. Sender identities are the ones the SMTP relay accepts.</div>
              <button class="ae-btn ae-btn--send ae-btn--full" :disabled="!activeTemplate" @click="openSend">
                <Icon name="mdi:send" /> Compose &amp; send
              </button>
            </div>
          </aside>

          <!-- Preview pane -->
          <main class="ae-main">
            <div class="ae-toolbar">
              <div class="ae-toolbar-left">
                <span class="ae-mono-label">Template:</span>
                <span class="ae-mono-val">{{ activeTemplate || '—' }}</span>
                <span class="ae-pill" :class="theme === 'neural' ? 'ae-pill--cyan' : 'ae-pill--red'">{{ theme.toUpperCase() }}</span>
                <span class="ae-pill ae-pill--muted">{{ format.toUpperCase() }}</span>
              </div>
              <div class="ae-toolbar-right">
                <span class="ae-mono-label">Bytes:</span>
                <span class="ae-mono-val">{{ byteSize }}</span>
                <button class="ae-btn ae-btn--ghost" :disabled="previewLoading || !activeTemplate" @click="renderPreview">↻</button>
              </div>
            </div>

            <div v-if="!activeTemplate" class="ae-empty">
              <div class="ae-empty-glyph"><Icon name="mdi:email-outline" /></div>
              <p class="ae-empty-title">Pick a template from the sidebar</p>
              <p class="ae-empty-sub">Each template ships in two themes (neural, sovereign) and two formats (HTML, plain text).</p>
            </div>

            <div v-else-if="previewError" class="ae-empty">
              <p class="ae-error-text"><Icon name="mdi:alert" /> {{ previewError }}</p>
              <button class="ae-btn ae-btn--ghost" @click="renderPreview">{{ t('adminEmailView.error.retry') }}</button>
            </div>

            <div v-else-if="previewLoading" class="ae-empty">
              <div class="ae-spinner"></div>
              <p class="ae-loading-text">Rendering…</p>
            </div>

            <div v-else class="ae-preview-wrap">
              <!-- HTML preview goes in a sandboxed iframe via srcdoc. The
                   `srcdoc` attribute renders the response as standalone HTML
                   without exposing it to the parent page (no script side
                   effects). Plain-text format uses a <pre>. -->
              <iframe
                v-if="format === 'html'"
                ref="iframeEl"
                class="ae-preview-iframe"
                :srcdoc="previewBody"
                sandbox="allow-same-origin"
                title="Email preview"
              ></iframe>
              <pre v-else class="ae-preview-text">{{ previewBody }}</pre>
            </div>
          </main>
        </div>

        <div class="ae-footer">
          <code>/admin/email/preview/{{ activeTemplate || '<template>' }}?theme={{ theme }}{{ format === 'text' ? '/text' : '' }}</code>
          <span> · {{ list.templates.length }} templates · 2 themes</span>
        </div>
      </template>
    </div>

    <!-- ── Send dialog (§2026-07-29b rebuild) ──────────────────────────────
         Two panes: compose on the left, a LIVE render on the right that uses
         the ACTUAL merged context — what this pane shows is byte-for-byte what
         the recipient receives, because both feed the same renderer. The old
         subtle "armed" label-swap silently ate a real send attempt; the confirm
         step is now a full-width state you cannot mistake for "sent". -->
    <Teleport to="body">
      <div v-if="sendOpen" class="ae-modal-backdrop" @click.self="closeSend">
        <div class="ae-modal ae-modal--wide" role="dialog" aria-modal="true">
          <div class="ae-modal-head">
            <div class="ae-modal-title"><Icon name="mdi:send" /> Send «{{ activeTemplate }}»</div>
            <button class="ae-modal-x" @click="closeSend" aria-label="Close">✕</button>
          </div>

          <!-- SENT state: an explicit receipt, so "did it go out?" is never a guess. -->
          <div v-if="sentReceipt" class="ae-sent">
            <div class="ae-sent-glyph"><Icon name="mdi:check-circle" /></div>
            <div class="ae-sent-title">Email sent</div>
            <div class="ae-sent-sub">via <strong>{{ activeSenderEmail }}</strong></div>
            <div class="ae-sent-list">
              <div v-for="r in sentReceipt.recipients" :key="r" class="ae-chip ae-chip--ok">{{ r }}</div>
            </div>
            <div class="ae-sent-subject">“{{ sentReceipt.subject }}”</div>
            <button class="ae-btn ae-btn--send" @click="closeSend">Close</button>
          </div>

          <div v-else class="ae-compose">
            <!-- ── left: compose form ── -->
            <div class="ae-compose-form">
              <label class="ae-field">
                <span class="ae-field-label">From identity</span>
                <div class="ae-sender-list">
                  <button
                    v-for="s in senders" :key="s.id"
                    class="ae-sender"
                    :class="{ 'ae-sender--active': sendSender === s.id, 'ae-sender--sov': s.theme === 'sovereign' }"
                    @click="pickSender(s)"
                  >
                    <span class="ae-sender-dot" :class="s.theme === 'sovereign' ? 'ae-theme-dot--sovereign' : 'ae-theme-dot--neural'"></span>
                    <span class="ae-sender-main">
                      <span class="ae-sender-mail">{{ s.from_email }}</span>
                      <span class="ae-sender-hint">{{ s.from_name }} · {{ s.hint }}</span>
                    </span>
                  </button>
                </div>
              </label>

              <label class="ae-field">
                <span class="ae-field-label">To <span class="ae-field-note">(comma-separated, max 10)</span></span>
                <input v-model="sendTo" type="text" class="ae-input" placeholder="name@company.com" />
                <div v-if="toChips.length" class="ae-chip-row">
                  <span v-for="c in toChips" :key="c.addr" class="ae-chip" :class="c.ok ? 'ae-chip--ok' : 'ae-chip--bad'">
                    {{ c.addr }}<template v-if="!c.ok"> ✕</template>
                  </span>
                </div>
              </label>

              <label class="ae-field">
                <span class="ae-field-label">CC <span class="ae-field-note">(optional)</span></span>
                <input v-model="sendCc" type="text" class="ae-input" />
                <div v-if="ccChips.length" class="ae-chip-row">
                  <span v-for="c in ccChips" :key="c.addr" class="ae-chip" :class="c.ok ? 'ae-chip--ok' : 'ae-chip--bad'">
                    {{ c.addr }}<template v-if="!c.ok"> ✕</template>
                  </span>
                </div>
              </label>

              <label class="ae-field">
                <span class="ae-field-label">Subject</span>
                <input v-model="sendSubject" type="text" class="ae-input" />
              </label>

              <div class="ae-field ae-field--grow">
                <span class="ae-field-label">Template context (JSON)
                  <span class="ae-field-note">edit fields like the real password — the preview updates live</span></span>
                <textarea v-model="sendContext" class="ae-ctx-editor ae-ctx-editor--tall" spellcheck="false"></textarea>
                <div v-if="ctxError" class="ae-send-err">{{ ctxError }}</div>
              </div>

              <div v-if="sendError" class="ae-send-err">{{ sendError }}</div>
            </div>

            <!-- ── right: the live envelope + rendered mail ── -->
            <div class="ae-compose-preview">
              <div class="ae-envelope">
                <div class="ae-env-row"><span class="ae-env-k">From</span>
                  <span class="ae-env-v">{{ activeSenderName }} &lt;{{ activeSenderEmail }}&gt;</span></div>
                <div class="ae-env-row"><span class="ae-env-k">To</span>
                  <span class="ae-env-v">{{ toChips.filter(c => c.ok).map(c => c.addr).join(', ') || '—' }}</span></div>
                <div class="ae-env-row" v-if="ccChips.some(c => c.ok)"><span class="ae-env-k">CC</span>
                  <span class="ae-env-v">{{ ccChips.filter(c => c.ok).map(c => c.addr).join(', ') }}</span></div>
                <div class="ae-env-row"><span class="ae-env-k">Subject</span>
                  <span class="ae-env-v ae-env-v--subject">{{ sendSubject || '—' }}</span></div>
                <div class="ae-env-tools">
                  <div class="ae-format-switch ae-format-switch--sm">
                    <button class="ae-format-btn" :class="{ 'ae-format-btn--active': liveFormat === 'html' }" @click="liveFormat = 'html'">HTML</button>
                    <button class="ae-format-btn" :class="{ 'ae-format-btn--active': liveFormat === 'text' }" @click="liveFormat = 'text'">TEXT</button>
                  </div>
                  <span class="ae-live-state" :class="{ 'ae-live-state--stale': liveStale }">
                    {{ livePending ? 'rendering…' : (liveStale ? 'render failed' : 'live · this is what will be sent') }}
                  </span>
                </div>
              </div>
              <div class="ae-live-body">
                <iframe v-if="liveFormat === 'html'" class="ae-live-iframe" :srcdoc="liveHtml"
                        sandbox="allow-same-origin" title="Live send preview"></iframe>
                <pre v-else class="ae-live-text">{{ liveText }}</pre>
              </div>
            </div>
          </div>

          <!-- ── footer: idle → CONFIRM (unmissable) → sending ── -->
          <div v-if="!sentReceipt" class="ae-modal-foot ae-modal-foot--col">
            <div v-if="armed" class="ae-confirm">
              <div class="ae-confirm-head"><Icon name="mdi:alert" /> Not sent yet — confirm the recipients:</div>
              <div class="ae-chip-row">
                <span v-for="c in toChips.filter(c => c.ok)" :key="c.addr" class="ae-chip ae-chip--ok">{{ c.addr }}</span>
                <span v-for="c in ccChips.filter(c => c.ok)" :key="'cc' + c.addr" class="ae-chip ae-chip--ok">CC {{ c.addr }}</span>
              </div>
            </div>
            <div class="ae-foot-btns">
              <button v-if="armed" class="ae-btn ae-btn--ghost" @click="armed = false" :disabled="sending">Back</button>
              <button v-else class="ae-btn ae-btn--ghost" @click="closeSend" :disabled="sending">Cancel</button>
              <button class="ae-btn ae-btn--send" :class="{ 'ae-btn--confirm': armed }"
                      :disabled="sending || !canSend" @click="doSend">
                <span v-if="sending" class="ae-btn-spin"></span>
                {{ sending ? 'Sending…' : (armed ? `CONFIRM — send to ${recipientCount} now` : 'Send email…') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
/**
 * AdminEmail — Email Studio
 *
 * Build #10 (2026-05-07). Pure-frontend on top of the existing email-preview
 * endpoints. Operator can browse all templates, switch themes (neural cyan
 * for transactional vs sovereign red for security alerts), see HTML or text,
 * and copy/download for documentation use.
 */
import { ref, computed, onMounted, watch } from 'vue'
import { useUIStore } from '@/stores/ui'
import { useI18n } from '@/composables/useI18n'
import {
  emailAdminService,
  emailSendService,
  emailPreviewWithContext,
  type EmailTheme,
  type EmailListResponse,
  type EmailSender,
} from '@/services/api/emailAdmin'

const { t } = useI18n()

const uiStore = useUIStore()

type Format = 'html' | 'text'

const list = ref<EmailListResponse | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const activeTemplate = ref<string>('')
const theme = ref<EmailTheme>('neural')
const format = ref<Format>('html')
const search = ref<string>('')

const previewBody = ref<string>('')
const previewLoading = ref(false)
const previewError = ref<string | null>(null)

const filteredTemplates = computed(() => {
  if (!list.value) return []
  const q = search.value.trim().toLowerCase()
  if (!q) return list.value.templates
  return list.value.templates.filter(t => t.toLowerCase().includes(q))
})

// §FESUITE (V0578): the size of the preview on screen, and nothing while there is none: it read "0 B" before the first
// render, and the previous template's size while a render was out or after one failed (the pane said so; the toolbar did not)
const byteSize = computed(() => {
  if (previewLoading.value || previewError.value || !previewBody.value) return '—'
  const n = new Blob([previewBody.value]).size
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} kB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
})

onMounted(loadList)

watch([activeTemplate, theme, format], () => {
  if (activeTemplate.value) renderPreview()
})

async function loadList() {
  loading.value = true
  error.value = null
  try {
    list.value = await emailAdminService.list()
    // Auto-select first non-_base template
    if (!activeTemplate.value && list.value.templates.length) {
      const firstReal = list.value.templates.find(t => !t.startsWith('_')) || list.value.templates[0]
      activeTemplate.value = firstReal
    }
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || 'Failed to list templates'
    uiStore.showError?.('Email', error.value!)
  } finally {
    loading.value = false
  }
}

async function renderPreview() {
  if (!activeTemplate.value) return
  previewLoading.value = true
  previewError.value = null
  try {
    if (format.value === 'html') {
      previewBody.value = await emailAdminService.previewHtml(activeTemplate.value, theme.value)
    } else {
      previewBody.value = await emailAdminService.previewText(activeTemplate.value)
    }
  } catch (e: any) {
    previewError.value = e?.response?.data?.detail || e?.message || 'Failed to render template'
  } finally {
    previewLoading.value = false
  }
}

function selectTemplate(t: string) {
  activeTemplate.value = t
}
function setTheme(t: EmailTheme) {
  if (theme.value === t) return
  theme.value = t
}
function setFormat(f: Format) {
  if (format.value === f) return
  format.value = f
}

async function copyHtml() {
  if (!previewBody.value) return
  try {
    await navigator.clipboard.writeText(previewBody.value)
    uiStore.showSuccess?.('Copied', `${activeTemplate.value} (${byteSize.value})`)
  } catch {
    uiStore.showError?.('Copy', 'Browser blocked clipboard write')
  }
}

function downloadHtml() {
  if (!previewBody.value) return
  const blob = new Blob([previewBody.value], { type: format.value === 'html' ? 'text/html' : 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `email-${activeTemplate.value}-${theme.value}.${format.value === 'html' ? 'html' : 'txt'}`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 4000)
  uiStore.showSuccess?.('Downloaded', `${a.download}`)
}

// ── §2026-07-29b — SEND dialog (compose + live merged-context preview) ──────
const sendOpen = ref(false)
const senders = ref<EmailSender[]>([])
const sendTheme = ref<EmailTheme>('neural')
const sendSender = ref<string>('noreply')
const sendTo = ref('')
const sendCc = ref('')
const sendSubject = ref('')
const sendContext = ref('{}')
const ctxError = ref('')
const sendError = ref('')
const sending = ref(false)
const armed = ref(false)
const sentReceipt = ref<{ recipients: string[]; subject: string } | null>(null)

// Live preview state: rendered from the MERGED context via the same backend
// renderer the send uses, so the pane cannot drift from the real send.
const liveFormat = ref<'html' | 'text'>('html')
const liveHtml = ref('')
const liveText = ref('')
const livePending = ref(false)
const liveStale = ref(false)
let liveTimer: ReturnType<typeof setTimeout> | null = null
let liveSeq = 0

const EMAIL_RX = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

const activeSenderEmail = computed(() =>
  senders.value.find(s => s.id === sendSender.value)?.from_email || '—')
const activeSenderName = computed(() =>
  senders.value.find(s => s.id === sendSender.value)?.from_name || 'TheProtocol')

function chips(raw: string) {
  return raw.split(',').map(s => s.trim()).filter(Boolean)
    .map(addr => ({ addr, ok: EMAIL_RX.test(addr) }))
}
const toChips = computed(() => chips(sendTo.value))
const ccChips = computed(() => chips(sendCc.value))
const recipientCount = computed(() =>
  toChips.value.filter(c => c.ok).length + ccChips.value.filter(c => c.ok).length)
const canSend = computed(() =>
  toChips.value.length > 0 &&
  toChips.value.every(c => c.ok) && ccChips.value.every(c => c.ok) &&
  !!sendSubject.value.trim() && !ctxError.value)

function parsedContext(): Record<string, any> | null {
  try {
    const c = sendContext.value.trim() ? JSON.parse(sendContext.value) : {}
    ctxError.value = ''
    return c
  } catch (e: any) {
    ctxError.value = `Context is not valid JSON: ${e?.message}`
    return null
  }
}

function scheduleLiveRender() {
  if (liveTimer) clearTimeout(liveTimer)
  liveTimer = setTimeout(renderLive, 550)
}

async function renderLive() {
  const ctx = parsedContext()
  if (ctx === null) { liveStale.value = true; return }
  const seq = ++liveSeq
  livePending.value = true
  try {
    const [html, text] = await Promise.all([
      emailPreviewWithContext.html(activeTemplate.value, sendTheme.value, ctx),
      emailPreviewWithContext.text(activeTemplate.value, ctx),
    ])
    if (seq !== liveSeq) return   // a newer edit superseded this render
    liveHtml.value = html
    liveText.value = text
    liveStale.value = false
  } catch {
    if (seq === liveSeq) liveStale.value = true
  } finally {
    if (seq === liveSeq) livePending.value = false
  }
}

watch([sendContext, sendTheme], scheduleLiveRender)

async function openSend() {
  if (!activeTemplate.value) return
  sendError.value = ''; ctxError.value = ''; armed.value = false; sentReceipt.value = null
  sendTheme.value = theme.value
  try {
    if (!senders.value.length) {
      const s = await emailSendService.senders()
      senders.value = s.senders
      if (!s.smtp_configured) sendError.value = 'MAIL_SERVER is not configured — sends will fail.'
    }
    if (senders.value.length && !senders.value.some(x => x.id === sendSender.value)) {
      sendSender.value = senders.value[0].id
    }
    const ctx = await emailSendService.sampleContext(activeTemplate.value)
    sendContext.value = JSON.stringify(ctx.context, null, 2)
    if (!sendSubject.value) sendSubject.value = ctx.suggested_subject
    sendOpen.value = true
    renderLive()
  } catch (e: any) {
    uiStore.showError?.('Send', e?.response?.data?.detail || e?.message || 'Could not open the send panel')
  }
}

function closeSend() {
  if (sending.value) return
  sendOpen.value = false
  armed.value = false
  sentReceipt.value = null
}

function pickSender(s: EmailSender) {
  sendSender.value = s.id
  sendTheme.value = s.theme         // chassis follows the identity's default
  theme.value = s.theme             // keep the studio preview behind the dialog in step
}

async function doSend() {
  sendError.value = ''
  const ctx = parsedContext()
  if (ctx === null) return
  if (!canSend.value) { sendError.value = 'Fix the highlighted recipients / subject first.'; return }

  // Step 1 arms an unmissable confirm state (recipients listed in the footer).
  if (!armed.value) { armed.value = true; return }

  sending.value = true
  try {
    const to = toChips.value.filter(c => c.ok).map(c => c.addr)
    const cc = ccChips.value.filter(c => c.ok).map(c => c.addr)
    const res = await emailSendService.send({
      template: activeTemplate.value,
      subject: sendSubject.value.trim(),
      recipients: to,
      cc: cc.length ? cc : undefined,
      theme: sendTheme.value,
      sender: sendSender.value,
      context: ctx,
    })
    sentReceipt.value = { recipients: [...res.recipients, ...cc.map(a => `CC ${a}`)], subject: sendSubject.value.trim() }
    armed.value = false
    uiStore.showSuccess?.('Email sent', `${res.template} → ${res.recipients.join(', ')}`)
  } catch (e: any) {
    sendError.value = e?.response?.data?.detail || e?.message || 'Send failed'
    armed.value = false
  } finally {
    sending.value = false
  }
}
</script>

<style scoped>
.ae {
  position: relative;
  min-height: 100vh;
  padding: 0 0 32px 0;
  color: rgba(255, 255, 255, 0.9);
  --cyan: var(--nc-primary, #00d2d2);
  --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --mono: 'IBM Plex Mono', 'Fira Code', monospace;
}

/* Ambient */
.ae-ambient { position: fixed; inset: 0; z-index: 0; pointer-events: none; overflow: hidden; }
.ae-grid {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(var(--cyan-rgb), 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--cyan-rgb), 0.03) 1px, transparent 1px);
  background-size: 60px 60px;
}
.ae-glow { position: absolute; border-radius: 50%; filter: blur(120px); opacity: 0.18; }
.ae-glow-1 { width: 420px; height: 420px; background: rgba(var(--cyan-rgb), 0.5); top: -100px; right: -80px; }
.ae-glow-2 { width: 320px; height: 320px; background: rgba(168, 85, 247, 0.4); bottom: -60px; left: -100px; }

/* Hero */
.ae-hero { position: relative; z-index: 1; padding: 36px 32px 18px; }
.ae-hero-inner { max-width: 1280px; margin: 0 auto; }
.ae-chip {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--mono); font-size: 10px; font-weight: 600;
  letter-spacing: 0.18em; color: var(--cyan);
  padding: 4px 12px;
  border: 1px solid rgba(var(--cyan-rgb), 0.25);
  border-radius: 14px;
  background: rgba(var(--cyan-rgb), 0.04);
  margin-bottom: 14px;
}
.ae-chip-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--cyan); box-shadow: 0 0 8px var(--cyan);
}
.ae-h1 {
  font-size: 2.1rem;
  margin: 0 0 0.4rem;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.95);
  letter-spacing: -0.01em;
}
.ae-accent { color: var(--cyan); text-shadow: 0 0 14px rgba(var(--cyan-rgb), 0.45); }
.ae-lead {
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.6);
  margin: 0;
  line-height: 1.5;
  max-width: 60rem;
}
.ae-lead code {
  background: rgba(var(--cyan-rgb), 0.08);
  color: var(--cyan);
  padding: 1px 5px; border-radius: 3px;
  font-size: 0.82em;
}

/* Body */
.ae-body {
  position: relative; z-index: 1;
  padding: 0 32px;
  max-width: 1400px;
  margin: 0 auto;
  display: flex; flex-direction: column; gap: 1.25rem;
}

.ae-btn {
  display: inline-flex; align-items: center; gap: 0.35rem;
  font-family: var(--mono); font-size: 0.65rem;
  letter-spacing: 0.08em; font-weight: 600;
  padding: 5px 12px; border-radius: 4px;
  border: 1px solid transparent;
  cursor: pointer; transition: all 0.15s;
}
.ae-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.ae-btn--ghost {
  background: transparent;
  border-color: rgba(var(--cyan-rgb), 0.25);
  color: rgba(var(--cyan-rgb), 0.85);
}
.ae-btn--ghost:hover:not(:disabled) {
  background: rgba(var(--cyan-rgb), 0.08);
  border-color: rgba(var(--cyan-rgb), 0.5);
  color: rgba(var(--cyan-rgb), 1);
}
.ae-btn--full { width: 100%; justify-content: center; margin-top: 0.3rem; }

/* Center */
.ae-center {
  text-align: center;
  padding: 5rem 1rem;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(var(--cyan-rgb), 0.12);
  border-radius: 6px;
}
.ae-spinner {
  width: 36px; height: 36px;
  border: 2.5px solid rgba(var(--cyan-rgb), 0.2);
  border-top-color: rgba(var(--cyan-rgb), 0.95);
  border-radius: 50%;
  animation: ae-spin 0.8s linear infinite;
  margin: 0 auto 0.8rem;
}
@keyframes ae-spin { to { transform: rotate(360deg); } }
.ae-loading-text {
  font-family: var(--mono); font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.5);
  letter-spacing: 0.1em; text-transform: uppercase;
}
.ae-error-text { font-family: var(--mono); font-size: 0.85rem; color: var(--nc-danger); }

/* Layout */
.ae-layout {
  display: grid;
  /* minmax(0, 1fr): the preview's 600 px iframe pans inside its own box; a 1fr track grew to it, and on a phone the
     whole page (the templates list too) ran ~190 px past the screen (the camera, 2026-10-13) */
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 1.25rem;
  min-height: 70vh;
}

/* Sidebar */
.ae-sidebar { display: flex; flex-direction: column; gap: 1rem; }
.ae-side-section {
  background: linear-gradient(180deg, rgba(10, 13, 22, 0.85), rgba(6, 8, 16, 0.85));
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 8px;
  padding: 0.85rem 0.95rem;
  display: flex; flex-direction: column; gap: 0.4rem;
}
.ae-side-title {
  font-family: var(--mono); font-size: 0.6rem;
  letter-spacing: 0.14em; font-weight: 700;
  color: var(--cyan); text-transform: uppercase;
  display: flex; justify-content: space-between; align-items: center;
}
.ae-side-count { color: rgba(255, 255, 255, 0.5); font-weight: 500; }
.ae-side-help {
  font-family: var(--mono); font-size: 0.62rem;
  color: rgba(255, 255, 255, 0.5);
  line-height: 1.5;
}
.ae-side-search {
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(var(--cyan-rgb), 0.2);
  color: rgba(255, 255, 255, 0.9);
  border-radius: 4px;
  font-family: var(--mono); font-size: 0.7rem;
  padding: 6px 9px; outline: none;
  transition: border-color 0.15s;
}
.ae-side-search:focus { border-color: rgba(var(--cyan-rgb), 0.55); }
.ae-side-list {
  display: flex; flex-direction: column; gap: 0.15rem;
  max-height: 50vh;
  overflow-y: auto;
}
.ae-side-item {
  display: flex; align-items: center; gap: 0.4rem;
  background: transparent; border: 1px solid transparent;
  border-radius: 4px;
  padding: 5px 9px;
  cursor: pointer;
  font-family: var(--mono); font-size: 0.65rem;
  color: rgba(255, 255, 255, 0.65);
  text-align: left;
  transition: all 0.12s;
  width: 100%;
}
.ae-side-item:hover {
  background: rgba(var(--cyan-rgb), 0.04);
  color: rgba(255, 255, 255, 0.9);
}
.ae-side-item--active {
  background: rgba(var(--cyan-rgb), 0.12);
  color: rgba(var(--cyan-rgb), 1);
  border-color: rgba(var(--cyan-rgb), 0.3);
}
.ae-side-item-glyph {
  color: var(--cyan); font-size: 0.75rem;
}
.ae-side-item-label {
  flex: 1;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}

/* Theme switch */
.ae-theme-switch {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
}
.ae-theme-btn {
  display: inline-flex; align-items: center; justify-content: center;
  gap: 0.4rem;
  background: transparent;
  border: 1px solid rgba(var(--cyan-rgb), 0.2);
  border-radius: 4px;
  padding: 6px 9px;
  cursor: pointer;
  font-family: var(--mono); font-size: 0.65rem; font-weight: 700;
  letter-spacing: 0.06em;
  color: rgba(255, 255, 255, 0.55);
  transition: all 0.15s;
}
.ae-theme-btn:hover {
  color: rgba(255, 255, 255, 0.95);
}
.ae-theme-btn--active {
  background: rgba(var(--cyan-rgb), 0.12);
  color: rgba(255, 255, 255, 0.95);
  border-color: rgba(var(--cyan-rgb), 0.45);
}
.ae-theme-btn--sovereign.ae-theme-btn--active {
  background: rgba(255, 51, 102, 0.12);
  border-color: rgba(255, 51, 102, 0.45);
  color: rgba(255, 51, 102, 1);
}
.ae-theme-dot {
  width: 7px; height: 7px; border-radius: 50%;
  flex-shrink: 0;
}
.ae-theme-dot--neural { background: var(--cyan); box-shadow: 0 0 5px var(--cyan); }
.ae-theme-dot--sovereign { background: #ff3366; box-shadow: 0 0 5px #ff3366; }

/* Format switch */
.ae-format-switch {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
}
.ae-format-btn {
  background: transparent;
  border: 1px solid rgba(var(--cyan-rgb), 0.2);
  border-radius: 4px;
  padding: 6px 9px;
  cursor: pointer;
  font-family: var(--mono); font-size: 0.65rem; font-weight: 600;
  letter-spacing: 0.06em;
  color: rgba(255, 255, 255, 0.55);
  transition: all 0.15s;
}
.ae-format-btn:hover { color: rgba(255, 255, 255, 0.9); }
.ae-format-btn--active {
  background: rgba(var(--cyan-rgb), 0.12);
  color: rgba(var(--cyan-rgb), 1);
  border-color: rgba(var(--cyan-rgb), 0.45);
}

/* Main panel */
.ae-main { display: flex; flex-direction: column; gap: 0.85rem; min-width: 0; }
.ae-toolbar {
  display: flex; justify-content: space-between; align-items: center;
  flex-wrap: wrap; gap: 0.85rem;
  padding: 0.6rem 0.85rem;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 6px;
}
.ae-toolbar-left, .ae-toolbar-right {
  display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;
}
.ae-mono-label {
  font-family: var(--mono); font-size: 0.6rem;
  letter-spacing: 0.1em;
  color: rgba(255, 255, 255, 0.45);
  text-transform: uppercase;
}
.ae-mono-val {
  font-family: var(--mono); font-size: 0.78rem;
  font-weight: 700;
  color: var(--cyan);
}

.ae-pill {
  font-family: var(--mono); font-size: 0.55rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  padding: 1px 6px;
  border-radius: 3px;
  border: 1px solid transparent;
}
.ae-pill--cyan  { background: rgba(var(--cyan-rgb), 0.1); color: var(--cyan); border-color: rgba(var(--cyan-rgb), 0.3); }
.ae-pill--red   { background: rgba(255, 51, 102, 0.1); color: var(--nc-danger, #ff3366); border-color: rgba(255, 51, 102, 0.3); }
.ae-pill--muted { background: rgba(var(--cyan-rgb), 0.05); color: rgba(255, 255, 255, 0.55); border-color: rgba(var(--cyan-rgb), 0.18); }

/* Empty */
.ae-empty {
  text-align: center;
  padding: 4rem 1rem;
  background: rgba(0, 0, 0, 0.25);
  border: 1px solid rgba(var(--cyan-rgb), 0.1);
  border-radius: 6px;
  display: flex; flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
}
.ae-empty-glyph {
  font-size: 2.5rem;
  color: rgba(var(--cyan-rgb), 0.4);
  font-family: var(--mono);
  margin-bottom: 0.4rem;
}
.ae-empty-title {
  font-family: var(--mono); font-size: 0.95rem;
  color: rgba(255, 255, 255, 0.85);
  margin-bottom: 0.4rem;
}
.ae-empty-sub {
  font-family: var(--mono); font-size: 0.7rem;
  color: rgba(255, 255, 255, 0.5);
  max-width: 32rem;
  line-height: 1.5;
}

/* Preview */
.ae-preview-wrap {
  position: relative;
  flex: 1;
  background: white;
  border: 1px solid rgba(var(--cyan-rgb), 0.2);
  border-radius: 6px;
  overflow: hidden;
  min-height: 60vh;
}
.ae-preview-iframe {
  width: 100%; height: 100%;
  border: none;
  background: white;
  display: block;
  min-height: 60vh;
}
.ae-preview-text {
  margin: 0;
  padding: 1rem 1.2rem;
  font-family: var(--mono);
  font-size: 0.78rem;
  color: #1a1a1a;
  background: #f8f8f8;
  white-space: pre-wrap;
  word-break: break-word;
  min-height: 60vh;
  border-radius: 4px;
}

/* Footer */
.ae-footer {
  font-family: var(--mono); font-size: 0.65rem;
  color: rgba(255, 255, 255, 0.5);
  padding-top: 0.5rem;
  border-top: 1px solid rgba(var(--cyan-rgb), 0.08);
}
.ae-footer code {
  background: rgba(var(--cyan-rgb), 0.08);
  color: var(--cyan);
  padding: 1px 5px;
  border-radius: 3px;
}

/* ── Send panel + modal (§2026-07-29) ── */
.ae-btn--send {
  background: rgba(var(--cyan-rgb), 0.14);
  border-color: rgba(var(--cyan-rgb), 0.5);
  color: rgba(var(--cyan-rgb), 1);
  font-weight: 700;
}
.ae-btn--send:hover:not(:disabled) {
  background: rgba(var(--cyan-rgb), 0.24);
  box-shadow: 0 0 14px rgba(var(--cyan-rgb), 0.25);
}
.ae-btn-spin {
  width: 11px; height: 11px; border-radius: 50%;
  border: 2px solid rgba(var(--cyan-rgb), 0.3);
  border-top-color: rgba(var(--cyan-rgb), 1);
  animation: ae-spin 0.7s linear infinite;
}
.ae-modal-backdrop {
  /* Above the dashboard sidebar shell (10000) and its toggle (10001) — at 4000
     the sidebar painted OVER the compose form's left column. */
  position: fixed; inset: 0; z-index: 10500;
  background: rgba(2, 4, 10, 0.78);
  backdrop-filter: blur(3px);
  display: flex; align-items: center; justify-content: center;
  padding: 18px;
}
.ae-modal {
  width: 560px; max-width: 100%;
  max-height: 92vh; overflow-y: auto;
  background: linear-gradient(180deg, rgba(12, 16, 26, 0.98), rgba(7, 10, 18, 0.98));
  border: 1px solid rgba(var(--cyan-rgb), 0.3);
  border-radius: 10px;
  box-shadow: 0 18px 60px rgba(0, 0, 0, 0.6);
}
.ae-modal-head {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 18px;
  border-bottom: 1px solid rgba(var(--cyan-rgb), 0.15);
}
.ae-modal-title {
  font-family: var(--mono); font-size: 0.85rem; font-weight: 700;
  color: rgba(255, 255, 255, 0.95);
  display: flex; align-items: center; gap: 0.5rem;
}
.ae-modal-x {
  background: transparent; border: none; cursor: pointer;
  color: rgba(255, 255, 255, 0.5); font-size: 0.9rem;
}
.ae-modal-x:hover { color: #fff; }
.ae-modal-body { padding: 16px 18px; display: flex; flex-direction: column; gap: 0.9rem; }
.ae-modal-foot {
  display: flex; justify-content: flex-end; gap: 0.6rem;
  padding: 12px 18px 16px;
  border-top: 1px solid rgba(var(--cyan-rgb), 0.12);
}
.ae-field { display: flex; flex-direction: column; gap: 0.35rem; }
.ae-field-label {
  font-family: var(--mono); font-size: 0.6rem; font-weight: 700;
  letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--cyan);
}
.ae-field-note { color: rgba(255, 255, 255, 0.4); font-weight: 500; text-transform: none; letter-spacing: 0.02em; }
.ae-input {
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(var(--cyan-rgb), 0.25);
  color: rgba(255, 255, 255, 0.92);
  border-radius: 5px;
  font-family: var(--mono); font-size: 0.76rem;
  padding: 8px 11px; outline: none;
}
.ae-input:focus { border-color: rgba(var(--cyan-rgb), 0.6); }
.ae-sender-list { display: flex; flex-direction: column; gap: 5px; }
.ae-sender {
  display: flex; align-items: center; gap: 0.6rem;
  background: rgba(0, 0, 0, 0.25);
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 6px;
  padding: 8px 11px;
  cursor: pointer; text-align: left;
  transition: all 0.13s;
}
.ae-sender:hover { border-color: rgba(var(--cyan-rgb), 0.4); }
.ae-sender--active {
  background: rgba(var(--cyan-rgb), 0.1);
  border-color: rgba(var(--cyan-rgb), 0.55);
}
.ae-sender--sov.ae-sender--active {
  background: rgba(255, 51, 102, 0.09);
  border-color: rgba(255, 51, 102, 0.5);
}
.ae-sender-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.ae-sender-main { display: flex; flex-direction: column; min-width: 0; }
.ae-sender-mail {
  font-family: var(--mono); font-size: 0.74rem; font-weight: 700;
  color: rgba(255, 255, 255, 0.92);
}
.ae-sender-hint { font-size: 0.64rem; color: rgba(255, 255, 255, 0.45); }
.ae-ctx-toggle {
  background: transparent; border: none; cursor: pointer;
  font-family: var(--mono); font-size: 0.66rem; font-weight: 700;
  letter-spacing: 0.08em; color: rgba(255, 255, 255, 0.6);
  display: flex; align-items: center; gap: 0.45rem;
  padding: 0; text-align: left;
}
.ae-ctx-toggle:hover { color: rgba(255, 255, 255, 0.9); }
.ae-ctx-editor {
  width: 100%; min-height: 190px; resize: vertical;
  background: rgba(0, 0, 0, 0.45);
  border: 1px solid rgba(var(--cyan-rgb), 0.22);
  border-radius: 6px;
  color: #b9e9f4;
  font-family: var(--mono); font-size: 0.7rem; line-height: 1.55;
  padding: 10px 12px; outline: none;
  box-sizing: border-box;
}
.ae-ctx-editor:focus { border-color: rgba(var(--cyan-rgb), 0.55); }
.ae-send-note {
  font-size: 0.68rem; line-height: 1.55;
  color: rgba(255, 255, 255, 0.55);
  border-left: 2px solid rgba(var(--cyan-rgb), 0.4);
  padding: 6px 10px;
  background: rgba(var(--cyan-rgb), 0.04);
  border-radius: 0 4px 4px 0;
}
.ae-send-err {
  font-family: var(--mono); font-size: 0.68rem;
  color: var(--nc-danger, #ff3366);
}

/* ── wide compose dialog (§2026-07-29b) ── */
.ae-modal--wide {
  width: min(1520px, 96vw);
  height: 92vh;
  display: flex; flex-direction: column;
  overflow: hidden;
}
.ae-compose {
  flex: 1; min-height: 0;
  display: grid;
  grid-template-columns: 400px 1fr;
  gap: 0;
}
.ae-compose-form {
  padding: 16px 18px;
  display: flex; flex-direction: column; gap: 0.85rem;
  overflow-y: auto;
  border-right: 1px solid rgba(var(--cyan-rgb), 0.12);
}
.ae-field--grow { flex: 1; min-height: 0; display: flex; }
.ae-ctx-editor--tall { flex: 1; min-height: 220px; }
.ae-compose-preview {
  display: flex; flex-direction: column; min-height: 0;
  background: rgba(0, 0, 0, 0.25);
}
.ae-envelope {
  padding: 12px 16px 10px;
  border-bottom: 1px solid rgba(var(--cyan-rgb), 0.15);
  display: flex; flex-direction: column; gap: 3px;
}
.ae-env-row { display: flex; gap: 0.7rem; align-items: baseline; }
.ae-env-k {
  font-family: var(--mono); font-size: 0.58rem; font-weight: 700;
  letter-spacing: 0.13em; text-transform: uppercase;
  color: rgba(255, 255, 255, 0.4);
  width: 54px; flex-shrink: 0; text-align: right;
}
.ae-env-v {
  font-family: var(--mono); font-size: 0.72rem;
  color: rgba(255, 255, 255, 0.85);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ae-env-v--subject { color: #fff; font-weight: 700; }
.ae-env-tools {
  display: flex; justify-content: space-between; align-items: center;
  margin-top: 7px;
}
.ae-format-switch--sm { grid-template-columns: auto auto; display: inline-grid; }
.ae-format-switch--sm .ae-format-btn { padding: 3px 10px; font-size: 0.58rem; }
.ae-live-state {
  font-family: var(--mono); font-size: 0.6rem;
  color: rgba(52, 211, 153, 0.85);
  letter-spacing: 0.06em;
}
.ae-live-state--stale { color: var(--nc-danger, #ff3366); }
.ae-live-body { flex: 1; min-height: 0; background: #fff; }
.ae-live-iframe { width: 100%; height: 100%; border: none; display: block; background: #fff; }
.ae-live-text {
  margin: 0; height: 100%; overflow: auto;
  padding: 1rem 1.2rem;
  font-family: var(--mono); font-size: 0.74rem;
  color: #1a1a1a; background: #f7f7f7;
  white-space: pre-wrap; word-break: break-word;
  box-sizing: border-box;
}
.ae-chip-row { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 2px; }
.ae-chip {
  font-family: var(--mono); font-size: 0.64rem; font-weight: 600;
  padding: 2px 9px; border-radius: 10px;
  border: 1px solid transparent;
}
.ae-chip--ok  { background: rgba(52, 211, 153, 0.1); color: #34d399; border-color: rgba(52, 211, 153, 0.35); }
.ae-chip--bad { background: rgba(255, 51, 102, 0.1); color: #ff3366; border-color: rgba(255, 51, 102, 0.4); }
.ae-modal-foot--col { flex-direction: column; align-items: stretch; gap: 0.7rem; }
.ae-foot-btns { display: flex; justify-content: flex-end; gap: 0.6rem; }
.ae-confirm {
  border: 1px solid rgba(245, 165, 36, 0.45);
  background: rgba(245, 165, 36, 0.07);
  border-radius: 6px;
  padding: 10px 13px;
  display: flex; flex-direction: column; gap: 7px;
}
.ae-confirm-head {
  font-family: var(--mono); font-size: 0.7rem; font-weight: 700;
  color: #f5a524;
  display: flex; align-items: center; gap: 0.45rem;
}
.ae-btn--confirm {
  background: rgba(245, 165, 36, 0.16);
  border-color: rgba(245, 165, 36, 0.6);
  color: #f5a524;
}
.ae-btn--confirm:hover:not(:disabled) { background: rgba(245, 165, 36, 0.26); }
.ae-sent {
  flex: 1;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 0.7rem; padding: 2rem;
  text-align: center;
}
.ae-sent-glyph { font-size: 2.6rem; color: #34d399; }
.ae-sent-title { font-family: var(--mono); font-size: 1.05rem; font-weight: 700; color: #fff; }
.ae-sent-sub { font-size: 0.78rem; color: rgba(255, 255, 255, 0.6); }
.ae-sent-list { display: flex; flex-wrap: wrap; gap: 6px; justify-content: center; }
.ae-sent-subject { font-family: var(--mono); font-size: 0.72rem; color: rgba(255, 255, 255, 0.55); max-width: 46rem; }
@media (max-width: 980px) {
  .ae-compose { grid-template-columns: 1fr; overflow-y: auto; }
  .ae-compose-form { border-right: none; border-bottom: 1px solid rgba(var(--cyan-rgb), 0.12); overflow: visible; }
  .ae-compose-preview { min-height: 60vh; }
}

/* Responsive */
@media (max-width: 1024px) {
  .ae-layout { grid-template-columns: minmax(0, 1fr); }
  .ae-sidebar { order: 2; }
  .ae-main { order: 1; }
}
@media (max-width: 768px) {
  .ae-hero { padding: 24px 16px 12px; }
  .ae-h1 { font-size: 1.5rem; }
  .ae-body { padding: 0 16px; }
}

/* Mobile pass follow-up (2026-05-08): the rendered email HTML inside the
   iframe has fixed widths (typical 600px email layout). On a 390px phone
   the wrap was overflow:hidden so content was clipped. Switch to scroll
   so users can pan inside the preview to see the full email. */
@media (max-width: 767.98px) {
  .ae-preview-wrap {
    overflow: auto !important;
    -webkit-overflow-scrolling: touch;
  }
  .ae-preview-iframe {
    width: 100%;
    /* Email designs typically need ≥600px. Keep min-width so the rendered
       HTML maintains its layout; the parent's overflow-x:auto lets the
       user pan horizontally. */
    min-width: 600px;
    min-height: 70vh;
  }
  .ae-preview-text {
    min-height: 50vh;
    font-size: 0.74rem;
  }
}
</style>
