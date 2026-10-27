<script setup lang="ts">
/**
 * BridgePayloadModal.vue — §BRIDGE R11 #7 + #11
 *
 * The raw wire, behind one gesture, in ONE component used by both live panels.
 *
 * His ask: *"left clicking it should pop up the json payload to inspect"* and
 * *"the payload itself. could be refined."*
 *
 * Two things are on screen at once, deliberately:
 *   · what the event CARRIED  — the envelope, verbatim, copyable;
 *   · what the bridge UNDERSTOOD — the fields the grammar actually read.
 * The keys in the first that appear in the second are marked, so the gap
 * between the payload and my reading of it is visible rather than assumed.
 * Every number here comes from the envelope; nothing is computed for display.
 */
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { usePrivacy } from '@/composables/usePrivacy'
import { grammarReadKeys, unwrapEnvelope, type VerbDescriptor } from '@/services/bridge/grammar'

const { t } = useI18n()
const { hidden: privacyHidden, money } = usePrivacy()
const props = defineProps<{
  show: boolean
  /** The descriptor whose envelope to inspect. */
  descriptor?: VerbDescriptor | null
  /** Or a bare envelope, for the ledger (which never builds a descriptor). */
  envelope?: unknown
  /** Row headline, so the modal names what you clicked. */
  title?: string | null
}>()
const emit = defineEmits<{ (e: 'close'): void }>()

const READ = grammarReadKeys()
const copied = ref(false)
const rawMode = ref(false)

const env = computed<any>(() => props.descriptor?.raw ?? props.envelope ?? null)
const inner = computed<any>(() => { try { return unwrapEnvelope(env.value) } catch { return null } })

const prettyJson = computed(() => {
  const e = env.value
  if (e == null) return ''
  try { return JSON.stringify(e, null, 2) } catch { return String(e) }
})

/**
 * Flatten one level of the payload so each key can be marked read/unread.
 *
 * ⚠ Polish pass 3 caught this by LOOKING at it: on this network the body
 * usually arrives as `data`, and often as a JSON **string**, not an object. The
 * first version expanded only an object-valued `payload`, so a real
 * `FxSwapSettled` showed six fields — four of them envelope metadata — while
 * `to`, `from`, `fee`, `rate` and `swap_id` sat unreadable inside one 300-char
 * line. Those are exactly the fields the grammar reads, so the "4 of these were
 * read" line was undercounting its own work, and the values a person opens this
 * panel FOR were the ones it hid.
 */
interface Field { key: string; value: string; read: boolean }
const fields = computed<Field[]>(() => {
  const i = inner.value
  if (!i || typeof i !== 'object') return []
  const src: Record<string, unknown> = { ...i }
  for (const key of ['payload', 'data', 'event_data']) {
    let body: any = (src as any)[key]
    if (typeof body === 'string') {
      const t = body.trim()
      if (t.startsWith('{')) { try { body = JSON.parse(t) } catch { body = null } } else body = null
    }
    if (body && typeof body === 'object' && !Array.isArray(body)) {
      delete (src as any)[key]
      // The envelope wins a collision: an inner `id` is not the event id.
      for (const [k, v] of Object.entries(body)) if (!(k in src)) (src as any)[k] = v
    }
  }
  const out: Field[] = []
  for (const [k, v] of Object.entries(src)) {
    let s: string
    if (v === null || v === undefined) s = String(v)
    else if (typeof v === 'object') { try { s = JSON.stringify(v) } catch { s = '[object]' } }
    else s = String(v)
    if (s.length > 220) s = s.slice(0, 217) + '...'
    out.push({ key: k, value: s, read: READ.has(k) })
  }
  // Read keys first — the ones that made the sentence you clicked on.
  out.sort((a, b) => (a.read === b.read ? a.key.localeCompare(b.key) : a.read ? -1 : 1))
  return out
})
const readCount = computed(() => fields.value.filter((f) => f.read).length)

/**
 * Escape closes it.
 *
 * Polish pass 2 caught this: `@keydown.esc` on the overlay never fires, because
 * a plain <div> is not focusable and the key event goes to whatever IS focused
 * — which, after clicking a row, is the row behind the overlay. A modal that
 * can only be dismissed with the mouse is a modal that traps a keyboard user.
 * Listener attaches only while open, and removes itself on unmount.
 */
function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape') { e.stopPropagation(); emit('close') }
}
watch(() => props.show, (open) => {
  if (typeof window === 'undefined') return
  if (open) window.addEventListener('keydown', onKey, true)
  else window.removeEventListener('keydown', onKey, true)
}, { immediate: true })
onBeforeUnmount(() => {
  if (typeof window !== 'undefined') window.removeEventListener('keydown', onKey, true)
})

async function copyRaw(): Promise<void> {
  try {
    await navigator.clipboard.writeText(prettyJson.value)
    copied.value = true
    setTimeout(() => { copied.value = false }, 1400)
  } catch {
    // Clipboard is permission-gated; the textarea below is always selectable,
    // so a refusal costs nothing and must not pretend to have succeeded.
    copied.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="show" class="bpm-overlay" data-testid="payload-modal" role="presentation"
         @click.self="emit('close')">
      <div class="bpm" role="dialog" aria-modal="true" aria-labelledby="bpm-title">
        <header class="bpm-hdr">
          <div class="bpm-hdr-l">
            <span id="bpm-title" class="bpm-title">{{ t('bridge.payload.title', 'EVENT PAYLOAD') }}</span>
            <span v-if="descriptor" class="bpm-type">{{ descriptor.eventType }}</span>
          </div>
          <button type="button" class="bpm-x" :aria-label="t('common.close', 'Close')" @click="emit('close')">&#10005;</button>
        </header>

        <p v-if="title" class="bpm-sentence">{{ title }}</p>

        <!-- What the bridge read out of it, when there is a descriptor. -->
        <div v-if="descriptor" class="bpm-read">
          <div class="bpm-read-row"><span>{{ t('bridge.payload.frame', 'FRAME') }}</span><b>{{ descriptor.frame }}</b></div>
          <div class="bpm-read-row"><span>{{ t('bridge.payload.verb', 'VERB') }}</span><b>{{ descriptor.verb }}</b></div>
          <div class="bpm-read-row"><span>{{ t('bridge.payload.when', 'WHEN') }}</span><b>{{ descriptor.ts }}</b></div>
          <div v-if="descriptor.amount !== null" class="bpm-read-row">
            <span>{{ t('bridge.payload.amount', 'AMOUNT') }}</span><b>{{ money(descriptor.amount) }} {{ descriptor.currency || '' }}</b>
          </div>
          <div v-if="descriptor.correlationKey" class="bpm-read-row">
            <span>{{ t('bridge.payload.corr', 'SEQUENCE') }}</span><b>{{ descriptor.correlationKey }}</b>
          </div>
        </div>

        <div class="bpm-tabs">
          <button type="button" class="bpm-tab" :class="{ 'is-on': !rawMode }"
                  data-testid="payload-fields" @click="rawMode = false">
            {{ t('bridge.payload.fields', 'FIELDS') }}
            <span class="bpm-tab-n">{{ fields.length }}</span>
          </button>
          <button type="button" class="bpm-tab" :class="{ 'is-on': rawMode }"
                  data-testid="payload-raw" @click="rawMode = true">
            {{ t('bridge.payload.raw', 'RAW JSON') }}
          </button>
          <span class="bpm-legend">
            <i class="bpm-dot"></i>{{ readCount }} {{ t('bridge.payload.readNote', 'of these were read by the bridge') }}
          </span>
          <button type="button" class="bpm-copy" data-testid="payload-copy" @click="copyRaw">
            {{ copied ? t('bridge.payload.copied', 'COPIED') : t('bridge.payload.copy', 'COPY JSON') }}
          </button>
        </div>

        <div v-if="!rawMode" class="bpm-body">
          <p v-if="!fields.length" class="bpm-empty">
            {{ t('bridge.payload.none', 'This row carries no inspectable envelope.') }}
          </p>
          <div v-for="f in fields" :key="f.key" class="bpm-field" :class="{ 'is-read': f.read }">
            <span class="bpm-k">{{ f.key }}</span>
            <span class="bpm-v">{{ privacyHidden ? '\u2022\u2022\u2022\u2022' : f.value }}</span>
          </div>
        </div>
        <div v-else class="bpm-body">
          <!-- R16.3 — the raw envelope is arbitrary JSON carrying amounts under
               keys that vary by event type. Masking numbers inside it would be
               guesswork, and a guess that misses is the leak. So it is
               WITHHELD while balances are hidden, and says so rather than
               rendering a blank box. -->
          <p v-if="privacyHidden" class="bpm-hidden" data-testid="bpm-raw-hidden">
            {{ t('bridge.payload.hidden', 'The raw envelope is hidden while amounts are hidden \u2014 it carries figures under keys that vary by event type. Turn amounts back on to inspect it.') }}
          </p>
          <textarea v-else class="bpm-raw" readonly spellcheck="false" :value="prettyJson"></textarea>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.bpm-overlay {
  position: fixed; top: 0; bottom: 0; z-index: 12000;
  /**
   * §BRIDGE R13 #10 — live INSIDE the stage column, so the rails stay readable.
   *
   * "the modals should not blcok the live ledger view." The bounds come from
   * `--brg-stage-l/r`, which Mission Control publishes on the ROOT element from
   * the measured `.brg-center` box (teleported content cannot inherit from
   * `.brg`). Both fall back to 0 — on a narrow window, or anywhere the bridge is
   * not mounted, this is an ordinary full-viewport modal again.
   */
  left: var(--brg-stage-l, 0px); right: var(--brg-stage-r, 0px);
  background: rgba(2, 5, 12, 0.72);
  display: flex; align-items: center; justify-content: center; padding: 1.2rem;
}
.bpm {
  width: min(760px, 96vw); max-height: 86vh; display: flex; flex-direction: column;
  background: var(--nc-bg-elev, #0a1018);
  border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.22)); border-radius: 6px;
  font-family: var(--nc-font-mono, ui-monospace, monospace);
  box-shadow: 0 18px 60px rgba(0, 0, 0, 0.55);
}
.bpm-hdr { display: flex; align-items: center; justify-content: space-between; padding: 0.6rem 0.8rem;
  border-bottom: 1px solid var(--nc-border, rgba(120, 160, 210, 0.16)); }
.bpm-hdr-l { display: flex; align-items: baseline; gap: 0.6rem; min-width: 0; }
.bpm-title { font-size: 0.68rem; letter-spacing: 0.18em; color: var(--nc-text, #d6e2f2); }
.bpm-type { font-size: 0.6rem; color: var(--nc-primary, #22d3ee); overflow: hidden; text-overflow: ellipsis; }
.bpm-x { background: none; border: 0; color: var(--nc-text-dim, #6b7f9e); cursor: pointer; font-size: 0.8rem; }
.bpm-x:hover { color: var(--nc-text, #d6e2f2); }
.bpm-sentence { margin: 0; padding: 0.5rem 0.8rem; font-size: 0.64rem; line-height: 1.5; color: var(--nc-text, #d6e2f2);
  border-bottom: 1px solid var(--nc-border, rgba(120, 160, 210, 0.1)); }
.bpm-read { display: flex; flex-wrap: wrap; gap: 0.35rem 1.1rem; padding: 0.5rem 0.8rem;
  border-bottom: 1px solid var(--nc-border, rgba(120, 160, 210, 0.1)); }
.bpm-read-row { display: flex; gap: 0.4rem; font-size: 0.58rem; }
.bpm-read-row span { color: var(--nc-text-dim, #6b7f9e); letter-spacing: 0.1em; }
.bpm-read-row b { color: var(--nc-text, #d6e2f2); font-weight: 600; }
.bpm-tabs { display: flex; align-items: center; gap: 0.4rem; padding: 0.45rem 0.8rem;
  border-bottom: 1px solid var(--nc-border, rgba(120, 160, 210, 0.1)); }
.bpm-tab { background: transparent; border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.18));
  border-radius: 3px; padding: 0.16rem 0.5rem; cursor: pointer;
  font-family: inherit; font-size: 0.55rem; letter-spacing: 0.1em; color: var(--nc-text-dim, #8fa3c0); }
.bpm-tab.is-on { color: var(--nc-primary, #22d3ee); border-color: color-mix(in srgb, var(--nc-primary, #22d3ee) 45%, transparent); }
.bpm-tab-n { opacity: 0.6; margin-left: 0.25rem; }
.bpm-legend { margin-left: auto; display: inline-flex; align-items: center; gap: 0.3rem;
  font-size: 0.52rem; color: var(--nc-text-dim, #6b7f9e); }
.bpm-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--nc-primary, #22d3ee); opacity: 0.8; display: inline-block; }
.bpm-copy { background: transparent; border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.18)); border-radius: 3px;
  padding: 0.16rem 0.5rem; cursor: pointer; font-family: inherit; font-size: 0.55rem; letter-spacing: 0.1em;
  color: var(--nc-text-dim, #8fa3c0); }
.bpm-copy:hover { color: var(--nc-primary, #22d3ee); }
.bpm-body { flex: 1 1 auto; min-height: 6rem; overflow: auto; padding: 0.5rem 0.8rem 0.8rem; }
.bpm-empty { font-size: 0.6rem; color: var(--nc-text-dim, #6b7f9e); }
.bpm-field { display: grid; grid-template-columns: 13rem 1fr; gap: 0.6rem; padding: 0.16rem 0;
  font-size: 0.58rem; line-height: 1.5; border-bottom: 1px dotted rgba(120, 160, 210, 0.08); }
.bpm-k { color: var(--nc-text-dim, #6b7f9e); overflow: hidden; text-overflow: ellipsis; }
.bpm-field.is-read .bpm-k { color: var(--nc-primary, #22d3ee); }
.bpm-field.is-read .bpm-k::before { content: '\25CF'; font-size: 0.5em; vertical-align: middle; margin-right: 0.35rem; }
.bpm-v { color: var(--nc-text, #d6e2f2); word-break: break-all; }
.bpm-hidden { margin: 0.6rem 0; font-size: 0.72rem; font-style: italic; color: var(--nc-text-muted, #6b7d8f); }
.bpm-raw { width: 100%; min-height: 24rem; background: rgba(4, 8, 14, 0.7);
  border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.14)); border-radius: 3px;
  color: var(--nc-text, #d6e2f2); font-family: inherit; font-size: 0.58rem; line-height: 1.5;
  padding: 0.5rem; resize: vertical; }
</style>
