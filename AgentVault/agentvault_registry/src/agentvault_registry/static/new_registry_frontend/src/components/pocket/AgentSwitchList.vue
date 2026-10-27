<!--
  §OURSTATE-6 — THE ONE AGENT LIST.

  There were two. The header's picker (search, scroll, the whole vault) and the
  composer's speaker picker (a bare v-for, no search, no scroll container). With
  640 stored credentials the second one was unusable — his words: "if i scroll
  the bottom selecter that says 'you' its not working. not scrollable. maybe
  list too large. top picker works really good with search functionality and
  proper scrolling."

  Worse than the ergonomics: the two controls held two SEPARATE selections, so
  the header could say "Acting as Trader Tilly" while the composer said "You".
  His ruling: *the 2 selectors should never be out of sync.* The only way two
  things cannot disagree is to make them one thing — so this list owns the
  choice, both mounts render it, and picking here sets the ACTING agent that
  every other surface already reads.

  `showYou` adds the human row for the composer, where speaking as yourself is a
  real option; the header has no use for it.
-->
<template>
  <div class="asl">
    <input v-if="credAgents.length > 5" v-model="q" class="asl-in" type="search"
           data-testid="asl-search"
           :placeholder="t('pocket.agentSheet.searchPh', 'Search name, DID or registry')" />

    <ul class="asl-list" data-testid="asl-list">
      <!-- The human. Always available where it means something: speaking as
           yourself needs no stored key, so it cannot be gated on having one. -->
      <li v-if="showYou">
        <button class="asl-row" :class="{ active: youSelected }" data-testid="asl-you"
                :disabled="switching" @click="emit('pick-you')">
          <span class="asl-row-main">
            <span class="asl-row-name">{{ t('ourstate.thread.speakerYou', 'You') }}</span>
            <span class="asl-row-sub">{{ t('ourstate.speaker.youSub', 'your own account') }}</span>
          </span>
          <span v-if="youSelected" class="asl-check"><Icon name="mdi:check-circle" /></span>
        </button>
      </li>
      <li v-for="ag in filtered" :key="ag.did">
        <button class="asl-row" :class="{ active: !youSelected && ag.did === activeDid }"
                data-testid="asl-row" :disabled="switching" @click="doSwitch(ag.did)">
          <span class="asl-row-main">
            <span class="asl-row-name">{{ ag.name || shorten(ag.did) }}</span>
            <span class="asl-row-sub">{{ hostLabel(ag.registry_url) }} · {{ shorten(ag.did) }}<template v-if="ag.viaSession">
              · <span data-testid="asl-via-session">{{ t('pocket.agentSheet.viaSession', 'yours, through your session') }}</span></template></span>
          </span>
          <span v-if="!youSelected && ag.did === activeDid" class="asl-check" data-testid="asl-active">
            <Icon name="mdi:check-circle" /></span>
        </button>
      </li>
    </ul>

    <!-- §PHONESTART (2026-09-02) — the old sentence sent the person to "the header agent switcher",
         which is where they were standing. An empty vault gets a door, not a circular direction. -->
    <div v-if="!credAgents.length" class="asl-note asl-warn" data-testid="asl-empty">
      <p>{{ sealedLocked ? noAgentReason : t('pocket.agentSheet.noneYet', 'No agent with stored credentials yet. Create one, or import one you already run.') }}</p>
      <button v-if="!sealedLocked" type="button" class="asl-create" data-testid="asl-create" @click="emit('create')">{{ t('pocket.agentSheet.createFirst', 'Create your wallet agent') }}</button>
    </div>
    <p v-else-if="q && !filtered.length" class="asl-note" data-testid="asl-nomatch">
      {{ t('pocket.agentSheet.noMatch', 'No stored credential matches that.') }}</p>

    <!-- Says how many of how many, so a search that hides 600 rows is legible
         rather than looking like a short vault. -->
    <p v-if="credAgents.length" class="asl-note" data-testid="asl-count">
      {{ q
         ? tp('pocket.agentSheet.showingOf', 'Showing {n} of {total}',
              { n: String(filtered.length), total: String(credAgents.length) })
         : viaSessionCount
           ? tp('pocket.agentSheet.actable', '{n} agents you can act as, {m} through your session',
                { n: String(credAgents.length), m: String(viaSessionCount) })
           : tp('pocket.agentSheet.stored', '{n} stored credentials', { n: String(credAgents.length) }) }}
    </p>
    <p v-if="msg" class="asl-note asl-warn" data-testid="asl-msg">{{ msg }}</p>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { usePocketAgent } from '@/composables/usePocketAgent'
import { useAuthStore } from '@/stores/auth'

const props = withDefaults(defineProps<{
  showYou?: boolean
  /** True when the human, not an agent, is the current choice. */
  youSelected?: boolean
}>(), { showYou: false, youSelected: false })

const emit = defineEmits<{ (e: 'switched', did: string): void; (e: 'pick-you'): void; (e: 'create'): void }>()

const { t, tp } = useI18n()
const auth = useAuthStore()
const { credAgents, ensureAgentFor, noAgentReason, sealedLocked } = usePocketAgent()

const q = ref('')
const switching = ref(false)
const msg = ref('')
const activeDid = computed<string>(() => (auth as any).activeAgent?.did || '')
// V0641: agents you own here with no saved secret are listed too (usePocketAgent viaSession): the count says so
const viaSessionCount = computed<number>(() => credAgents.value.filter(a => a.viaSession).length)

const filtered = computed(() => {
  const needle = q.value.trim().toLowerCase()
  if (!needle) return credAgents.value
  return credAgents.value.filter(a =>
    (a.name || '').toLowerCase().includes(needle)
    || a.did.toLowerCase().includes(needle)
    || (a.registry_url || '').toLowerCase().includes(needle))
})

const shorten = (d: string) => (d && d.length > 26 ? `${d.slice(0, 16)}…${d.slice(-6)}` : d)
/** `URL.host` carries the PORT; hostname is what a human reads. (§FOREIGNDEV) */
function hostLabel(u?: string | null): string {
  if (!u) return t('pocket.send.thisRegistry', 'this registry')
  try { return new URL(u).hostname } catch { return u }
}

async function doSwitch(did: string) {
  msg.value = ''
  switching.value = true
  try {
    const ok = await ensureAgentFor(did)
    if (ok) {
      try { localStorage.setItem('activeAgentId', did) } catch { /* the choice still holds for this session */ }
      emit('switched', did)
    } else {
      msg.value = t('pocket.agentSheet.switchFailed',
                    'Could not sign in as that agent — its credential may be stale or belong to an unreachable registry.')
    }
  } catch (e: any) {
    msg.value = e?.detail || String(e)
  } finally { switching.value = false }
}
</script>

<style scoped>
.asl { display: flex; flex-direction: column; gap: 0.55rem; min-height: 0; }
.asl-in { width: 100%; min-height: 44px; font-size: 16px; padding: 0 12px; border-radius: 10px;
  border: 1px solid var(--border-color, rgba(128,128,128,.25)); background: transparent; color: inherit; }
/* THE SCROLL CONTAINER. Its absence is the whole bug: 640 rows in a flex column
   with no bound simply ran off the sheet. `min-height: 0` is load-bearing — a
   flex child will not shrink below its content without it, and the overflow
   then never engages. */
.asl-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.4rem;
  max-height: 52vh; overflow-y: auto; min-height: 0; -webkit-overflow-scrolling: touch; overscroll-behavior: contain; }
.asl-row { width: 100%; display: flex; align-items: center; gap: 10px; min-height: 52px; padding: 6px 10px;
  border-radius: 10px; cursor: pointer; text-align: left; color: inherit;
  border: 1px solid var(--border-color, rgba(128,128,128,.2)); background: none; }
.asl-row.active { background: var(--accent-soft, rgba(120,160,255,.16)); border-color: var(--accent, #4da3ff); }
.asl-row-main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.asl-row-name { font-weight: 700; }
.asl-row-sub { font-size: .72rem; opacity: .6; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.asl-check { opacity: .9; }
.asl-note { margin: 0; font-size: .78rem; opacity: .7; }
.asl-warn { color: var(--danger, #e0716b); }
.asl-note p { margin: 0 0 0.45rem; }
.asl-create { font-size: 0.8rem; font-weight: 600; padding: 0.45rem 0.9rem; border-radius: 8px; cursor: pointer;
  border: 1px solid rgba(var(--nc-primary-rgb, 0,229,255), 0.5); background: transparent; color: var(--nc-primary, #00e5ff); }
</style>
