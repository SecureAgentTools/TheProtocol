<script setup lang="ts">
// Multi-Frame Console — a session on every registry you hold an account on, from this console.
//
// §FEFRAME W3 (V0504): the list is the FRAME MANIFEST's peers (frames AND operators, from the server's one resolver),
// never the admin relay's targets (empty on every live registry: its candidate keys were the literal A/B/C) nor a
// name regex. Signing in happens AT the peer's own API (direct), for an admin and a non-admin alike, and the card says
// so before you type ("you are signing in to Y from X's console"). The session is the session hub's
// (stores/sessions.ts): its own refresh token, the road it came in on remembered for the tab, so a reload reconnects
// directly. Acting as an agent you own there needs no secret (the owner rail); a saved or typed secret is the road for
// an agent you do not own through that account.
import { ref, reactive, computed, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useSessionHub } from '@/stores/sessions'
import { useFrameManifest } from '@/composables/useFrameManifest'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { describeCurrency } from '@/config/currencies'
import { signInSentence } from '@/services/sessionHub'
import type { FrameEntry } from '@/services/frameManifest'
import { peerListAgents, type PeerAgent } from '@/services/api/peer'
import { getRegistryDirectoryOrPublic, type RegistryDirectory } from '@/services/api/command'
import VaultImportModal from '@/components/command/VaultImportModal.vue'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'

const auth = useAuthStore()
const hub = useSessionHub()
const fm = useFrameManifest()
const { readFailed: cfgReadFailed, reload: cfgReload } = useRegistryConfig()

interface PeerCard {
  key: string
  label: string
  sub: string
  accent: string
  role: 'frame' | 'operator'
  /** that registry's own API origin; null => this console cannot reach it directly */
  baseUrl: string | null
}

const here = computed(() => fm.self.value?.display_name || fm.self.value?.name || 'this registry')

function cardOf(e: FrameEntry): PeerCard {
  const ccy = e.currency ? describeCurrency(e.currency) : null
  const parent = e.parent ? (fm.byKey(e.parent)?.display_name || e.parent) : null
  return {
    key: e.key,
    label: e.display_name || e.name || e.key,
    sub: e.role === 'operator'
      ? `cloud operator${parent ? ' of ' + parent : ''}${e.currency ? ' · ' + e.currency : ''}`
      : `frame${e.currency ? ' · ' + e.currency : ''}`,
    accent: ccy?.accent || 'var(--nc-text-dim, #7a8a9a)',
    role: e.role,
    baseUrl: e.public_url || e.console_url || null,
  }
}

const PEER_FRAMES = computed<PeerCard[]>(() => fm.peers.value.filter(e => e.role === 'frame').map(cardOf))
const PEER_OPS = computed<PeerCard[]>(() => fm.peers.value.filter(e => e.role === 'operator').map(cardOf))
const noPeers = computed(() => fm.settled.value && fm.known.value && fm.peers.value.length === 0)
// §FESUITE (2026-10-05): "no manifest" is the registry's own answer (an older registry), so it waits for a config that was
// read; a config read that failed is said as one (it read "an older registry" before), and a read that answers later
// brings the manifest in (useFrameManifest adopts it)
const noManifest = computed(() => fm.settled.value && !fm.known.value && !cfgReadFailed.value)
const manifestReadFailed = computed(() => fm.settled.value && !fm.known.value && cfgReadFailed.value)

const showOps = ref(false)
const visibleCards = computed<PeerCard[]>(() =>
  showOps.value || PEER_FRAMES.value.length === 0 ? [...PEER_FRAMES.value, ...PEER_OPS.value] : PEER_FRAMES.value)

interface FormState {
  email: string
  password: string
  agents: PeerAgent[]
  loadingAgents: boolean
  agentsRead: 'idle' | 'loading' | 'ok' | 'failed'
  selectedClientId: string
  agentSecret: string
  acting: string | null
}
const forms = reactive<Record<string, FormState>>({})
function form(k: string): FormState {
  if (!forms[k]) forms[k] = { email: '', password: '', agents: [], loadingAgents: false, agentsRead: 'idle', selectedClientId: '', agentSecret: '', acting: null }
  return forms[k]
}

/*
 * §BRIDGE R10 — the vault import lives here (his word). It writes to the session hub, so one import connects every
 * surface at once: this console, the command centre, and Mission Control's idea of which agents are yours.
 */
const dir = ref<RegistryDirectory | null>(null)
const vaultOpen = ref(false)
const vaultNote = ref<string | null>(null)
function onVaultImported(summary: string) {
  // the modal stays open with its per-line report (a refused line says why there); the summary waits beside the button
  vaultNote.value = summary
  for (const c of [...PEER_FRAMES.value, ...PEER_OPS.value]) if (hub.isConnected(c.key)) void loadAgents(c.key)
}

const reconnected = ref(0)
onMounted(async () => {
  void getRegistryDirectoryOrPublic().then(r => { dir.value = r.directory }).catch(() => { dir.value = null })
  // A reload: every session this tab remembers reconnects AT its registry (its own refresh token).
  reconnected.value = await hub.reconnectRemembered()
  const email = (auth.user as any)?.email || ''
  for (const c of [...PEER_FRAMES.value, ...PEER_OPS.value]) {
    const f = form(c.key)
    f.email = hub.sessionFor(c.key).adminEmail || email
    if (hub.isConnected(c.key)) void loadAgents(c.key)
  }
})

async function doLogin(c: PeerCard) {
  const f = form(c.key)
  const ok = await hub.connectAdmin(c.key, f.email.trim(), f.password, c.baseUrl)
  f.password = ''                  // never kept, success or not
  if (ok) void loadAgents(c.key)
}

/** The agents you own there: GET /developers/me/agents with THAT registry's session. */
async function loadAgents(k: string) {
  const f = form(k)
  f.loadingAgents = true
  // §FESUITE (2026-10-05): a failed read said "You own no agents on <peer> through this account"; it says the read failed
  // now, with Try again, and a failed refresh (after a vault import) keeps the list that was shown
  if (f.agentsRead !== 'ok') f.agentsRead = 'loading'
  try {
    const client = hub.registryClient(k)
    if (client) {
      const r = await client.get('/developers/me/agents')
      const rows: any[] = Array.isArray(r.data) ? r.data : (r.data?.agents || [])
      f.agents = rows.map((a: any) => ({ name: a.name || a.did, did: a.did, client_id: a.client_id || null } as PeerAgent))
    } else {
      const tok = hub.adminTokenFor(k)
      f.agents = tok ? await peerListAgents(k, tok, null) : []
    }
    f.agentsRead = 'ok'
  } catch {
    if (f.agentsRead !== 'ok') { f.agents = []; f.agentsRead = 'failed' }
  } finally {
    f.loadingAgents = false
  }
}

/** Act as an agent you own there: the owner rail, no secret. */
async function actAs(k: string, did: string) {
  const f = form(k)
  f.acting = did
  try { await hub.ensureAgentToken(k, did) } finally { f.acting = null }
}

/** An agent you do not own through this account: its client id and secret, minted where it lives. */
async function doAgentSecret(k: string) {
  const f = form(k)
  const picked = f.agents.find(a => a.client_id === f.selectedClientId)
  const did = picked?.did || f.selectedClientId.trim()
  const tok = await hub.mintAgentToken(k, f.selectedClientId.trim(), f.agentSecret, did)
  if (tok) f.agentSecret = ''
}

function activeAgentLabel(k: string): string | null {
  const a = hub.activeAgentFor(k)
  if (!a) return null
  const row = form(k).agents.find(x => x.did === a.did)
  return row?.name || a.did
}

function disconnect(k: string) {
  hub.disconnect(k)
  const f = form(k); f.password = ''; f.agentSecret = ''; f.selectedClientId = ''; f.agents = []; f.agentsRead = 'idle'
}
</script>

<template>
  <div class="mfc">
    <div class="mfc-intro">
      <Icon name="mdi:layers" class="mfc-intro-glyph" />
      <div>
        <h3 class="mfc-title">Multi-Frame Console</h3>
        <p class="mfc-sub">
          Hold a session on every registry of this federation you have an account on, from {{ here }}'s console.
          Each sign-in happens at that registry itself; passwords are used once and never stored, and a session is
          kept for this browser tab only. Your sign-in here is unchanged.
        </p>
        <p v-if="reconnected" class="mfc-sub mfc-sub--ok" data-testid="mfc-reconnected">
          {{ reconnected }} session{{ reconnected === 1 ? '' : 's' }} reconnected from this tab.
        </p>
      </div>
    </div>

    <div class="mfc-bulk">
      <button type="button" class="mfc-bulk-btn" data-testid="mfc-vault-import" @click="vaultOpen = true">
        <Icon name="mdi:file-key-outline" :size="14" />
        <span>Import / export registry vault</span>
      </button>
      <span class="mfc-bulk-hint">
        A JSON file of the registries you hold accounts on: one import connects them all.
        Passwords are used once to open a session and are never stored.
      </span>
      <span v-if="vaultNote" class="mfc-bulk-note" data-testid="mfc-vault-note">{{ vaultNote }}</span>
    </div>

    <VaultImportModal
      :show="vaultOpen"
      :directory="dir"
      @close="vaultOpen = false"
      @imported="onVaultImported"
    />

    <ReadFailedNotice v-if="manifestReadFailed" :retry="cfgReload" />
    <div v-else-if="noManifest" class="mfc-none" data-testid="mfc-no-manifest">
      <Icon name="mdi:layers" class="mfc-none-ico" />
      <div>
        <strong>This registry did not say who its federation peers are.</strong>
        <p class="mfc-none-sub">
          Its public configuration carries no frame manifest (an older registry), so this console names no peers
          rather than guessing them.
        </p>
      </div>
    </div>
    <div v-else-if="noPeers" class="mfc-none" data-testid="mfc-no-peers">
      <Icon name="mdi:layers" class="mfc-none-ico" />
      <div>
        <strong>{{ here }} has no active federation peers.</strong>
        <p class="mfc-none-sub">
          There is no other registry to sign in to from here. Admin views operate on this registry's own ledger.
        </p>
      </div>
    </div>

    <div class="mfc-grid">
      <section v-for="c in visibleCards" :key="c.key" class="mfc-card" :data-peer="c.key">
        <header class="mfc-card-head">
          <span class="mfc-dot" :style="{ background: c.accent }"></span>
          <span class="mfc-card-title">{{ c.label }}</span>
          <span class="mfc-card-sub">{{ c.sub }}</span>
          <span class="mfc-status" :class="hub.isConnected(c.key) ? 'mfc-status--on' : 'mfc-status--off'">
            {{ hub.isConnected(c.key) ? 'connected' : hub.sessionFor(c.key).status === 'connecting' ? 'connecting' : 'not connected' }}
          </span>
        </header>

        <div v-if="!hub.isConnected(c.key)" class="mfc-block">
          <p class="mfc-where" data-testid="mfc-where">{{ signInSentence(c.label, here) }}</p>
          <p v-if="!c.baseUrl" class="mfc-err">This console does not know {{ c.label }}'s address, so it cannot sign in there.</p>
          <label class="mfc-label">Email at {{ c.label }}
            <input v-model="form(c.key).email" class="mfc-input" type="email" autocomplete="off" placeholder="you@…" />
          </label>
          <label class="mfc-label">Password at {{ c.label }}
            <input v-model="form(c.key).password" class="mfc-input" type="password" autocomplete="off"
                   placeholder="••••••••" @keyup.enter="doLogin(c)" />
          </label>
          <button class="mfc-btn mfc-btn--primary" data-testid="mfc-connect"
                  :disabled="!c.baseUrl || hub.sessionFor(c.key).status === 'connecting' || !form(c.key).email || !form(c.key).password"
                  @click="doLogin(c)">
            {{ hub.sessionFor(c.key).status === 'connecting' ? 'Signing in…' : `Sign in to ${c.label}` }}
          </button>
        </div>

        <div v-else class="mfc-block">
          <div class="mfc-ok" data-testid="mfc-connected">
            <Icon name="mdi:check-circle" class="mfc-ok-glyph" />
            Signed in at {{ c.label }} as <strong>{{ hub.sessionFor(c.key).adminEmail }}</strong>
            <span class="mfc-via">({{ hub.sessionFor(c.key).via === 'direct' ? 'directly' : 'through the admin relay' }})</span>
          </div>

          <div class="mfc-agent">
            <div class="mfc-agent-head">
              <Icon name="mdi:robot" class="mfc-agent-glyph" />
              <span>Act as an agent on {{ c.label }} (optional)</span>
            </div>
            <div v-if="activeAgentLabel(c.key)" class="mfc-ok mfc-ok--agent" data-testid="mfc-agent-active">
              <Icon name="mdi:check-circle" class="mfc-ok-glyph" />
              Acting as <strong>{{ activeAgentLabel(c.key) }}</strong>
              <span class="mfc-via">({{ hub.sessionFor(c.key).agentVia[hub.activeAgentFor(c.key)!.did] === 'owner' ? 'your own agent, no secret' : 'by its secret' }})</span>
            </div>
            <ul v-if="form(c.key).agents.length" class="mfc-agents">
              <li v-for="a in form(c.key).agents" :key="a.did || a.client_id || a.name">
                <span class="mfc-agent-name">{{ a.name }}</span>
                <button v-if="a.did" class="mfc-btn" data-testid="mfc-act-as" :disabled="form(c.key).acting === a.did"
                        @click="actAs(c.key, a.did)">
                  {{ form(c.key).acting === a.did ? 'Signing in…' : 'Act as' }}
                </button>
                <span v-if="a.did && hub.lastAgentError[a.did]" class="mfc-err">{{ hub.lastAgentError[a.did] }}</span>
              </li>
            </ul>
            <ReadFailedNotice v-else-if="form(c.key).agentsRead === 'failed'" dense :retry="() => loadAgents(c.key)" />
            <p v-else class="mfc-sub">{{ form(c.key).agentsRead === 'ok' ? 'You own no agents on ' + c.label + ' through this account.' : 'Loading your agents there…' }}</p>
            <details class="mfc-secret">
              <summary>An agent you do not own through this account (its client id and secret)</summary>
              <label class="mfc-label">Client ID
                <input v-model="form(c.key).selectedClientId" class="mfc-input" type="text" placeholder="agent client_id" />
              </label>
              <label class="mfc-label">Client secret
                <input v-model="form(c.key).agentSecret" class="mfc-input" type="password" autocomplete="off"
                       placeholder="agent client_secret" @keyup.enter="doAgentSecret(c.key)" />
              </label>
              <button class="mfc-btn" :disabled="!form(c.key).selectedClientId || !form(c.key).agentSecret"
                      @click="doAgentSecret(c.key)">Sign in as this agent</button>
            </details>
          </div>

          <button class="mfc-btn mfc-btn--ghost" @click="disconnect(c.key)">Sign out of {{ c.label }}</button>
        </div>

        <div v-if="hub.sessionFor(c.key).error" class="mfc-err">{{ hub.sessionFor(c.key).error }}</div>
      </section>
    </div>

    <button v-if="PEER_OPS.length && PEER_FRAMES.length" type="button" class="mfc-ops-toggle" @click="showOps = !showOps">
      <Icon :name="showOps ? 'arrow-down' : 'chevron-right'" class="mfc-ops-caret" />
      Cloud operators ({{ PEER_OPS.length }})
    </button>
  </div>
</template>

<style scoped>
.mfc-sub--ok { color: #34d399; margin-top: 4px; }
.mfc-where { margin: 0; font-size: 0.74rem; color: rgba(230, 249, 255, 0.62); line-height: 1.45; }
.mfc-via { font-size: 0.7rem; opacity: 0.6; margin-left: 4px; }
.mfc-agents { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.mfc-agents li { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.mfc-agent-name { font-size: 0.8rem; flex: 1 1 auto; min-width: 0; overflow-wrap: anywhere; }
.mfc-secret summary { cursor: pointer; font-size: 0.72rem; color: rgba(230, 249, 255, 0.55); }
.mfc-secret[open] { display: flex; flex-direction: column; gap: 8px; }
.mfc-bulk {
  display: flex; align-items: center; gap: .6rem; flex-wrap: wrap;
  margin: 0 0 1rem; padding: .6rem .75rem;
  border: 1px dashed var(--nc-border, rgba(120,160,210,.25));
  border-radius: 6px; background: rgba(120,160,210,.04);
}
.mfc-bulk-btn {
  display: inline-flex; align-items: center; gap: .4rem;
  padding: .35rem .7rem; border-radius: 4px; cursor: pointer;
  border: 1px solid var(--nc-primary, #22d3ee);
  background: color-mix(in srgb, var(--nc-primary, #22d3ee) 12%, transparent);
  color: var(--nc-primary, #22d3ee); font-size: .78rem; font-weight: 600;
}
.mfc-bulk-btn:hover { background: color-mix(in srgb, var(--nc-primary, #22d3ee) 22%, transparent); }
.mfc-bulk-hint { font-size: .72rem; color: var(--nc-text-dim, #6b7f9e); flex: 1 1 16rem; }
.mfc-bulk-note { font-size: .72rem; color: var(--nc-success, #34d399); }

.mfc { display: flex; flex-direction: column; gap: 16px; }
.mfc-intro { display: flex; gap: 12px; align-items: flex-start; }
.mfc-intro-glyph { width: 26px; height: 26px; color: var(--nc-primary, #00d2d2); flex: 0 0 26px; margin-top: 2px; }
.mfc-title { margin: 0 0 4px; font-size: 1rem; font-weight: 700; }
.mfc-sub { margin: 0; font-size: 0.8rem; color: rgba(230, 249, 255, 0.6); line-height: 1.5; max-width: 70ch; }
.mfc-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 14px; }
.mfc-card { background: rgba(8, 12, 20, 0.55); border: 1px solid rgba(var(--nc-primary-rgb), 0.14); border-radius: 12px; padding: 16px; }
.mfc-card-head { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.mfc-dot { width: 10px; height: 10px; border-radius: 50%; flex: 0 0 10px; }
.mfc-card-title { font-weight: 700; }
.mfc-card-sub { font-size: 0.7rem; opacity: 0.5; }
.mfc-status { margin-left: auto; font-size: 0.62rem; text-transform: uppercase; letter-spacing: 0.08em; padding: 2px 8px; border-radius: 10px; }
.mfc-status--on { color: #00e676; border: 1px solid rgba(0, 230, 118, 0.35); }
.mfc-status--off { color: rgba(230, 249, 255, 0.4); border: 1px solid rgba(255, 255, 255, 0.1); }
.mfc-block { display: flex; flex-direction: column; gap: 10px; }
.mfc-label { display: flex; flex-direction: column; gap: 4px; font-size: 0.72rem; color: rgba(230, 249, 255, 0.7); }
.mfc-input { background: rgba(0, 0, 0, 0.3); border: 1px solid rgba(var(--nc-primary-rgb), 0.2); border-radius: 7px; padding: 8px 10px; color: #e6f9ff; font-size: 0.82rem; }
.mfc-input:focus-visible { outline: 2px solid rgba(var(--nc-primary-rgb), 0.5); outline-offset: 1px; }
.mfc-btn { align-self: flex-start; padding: 8px 16px; border-radius: 7px; border: 1px solid rgba(var(--nc-primary-rgb), 0.4); background: rgba(var(--nc-primary-rgb), 0.1); color: rgba(var(--nc-primary-rgb), 1); font-weight: 600; cursor: pointer; font-size: 0.8rem; }
.mfc-btn:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb), 0.18); }
.mfc-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.mfc-btn--primary { border-color: rgba(0, 230, 118, 0.5); background: rgba(0, 230, 118, 0.12); color: #00e676; }
.mfc-btn--ghost { border-color: rgba(255, 255, 255, 0.15); background: transparent; color: rgba(230, 249, 255, 0.6); font-weight: 400; }
.mfc-ok { display: flex; align-items: center; gap: 6px; font-size: 0.82rem; color: #00e676; }
.mfc-ok--agent { color: #7fdfff; }
.mfc-ok-glyph { width: 16px; height: 16px; flex: 0 0 16px; }
.mfc-agent { border-top: 1px solid rgba(255, 255, 255, 0.07); padding-top: 12px; display: flex; flex-direction: column; gap: 10px; }
.mfc-agent-head { display: flex; align-items: center; gap: 6px; font-size: 0.74rem; color: rgba(230, 249, 255, 0.6); }
.mfc-agent-glyph { width: 16px; height: 16px; flex: 0 0 16px; color: #ff9d3c; }
.mfc-err { margin-top: 10px; font-size: 0.78rem; color: #ff8a80; }
.mfc-none {
  display: flex; gap: 12px; align-items: flex-start; padding: 18px;
  border: 1px dashed rgba(var(--nc-primary-rgb), 0.25); border-radius: 12px;
  color: rgba(230, 249, 255, 0.75); font-size: 0.85rem;
}
.mfc-none-ico { width: 22px; height: 22px; color: rgba(var(--nc-primary-rgb), 0.6); flex: 0 0 22px; }
.mfc-none-sub { margin: 4px 0 0; font-size: 0.76rem; color: rgba(230, 249, 255, 0.5); line-height: 1.5; }
.mfc-ops-toggle {
  display: inline-flex; align-items: center; gap: 6px; align-self: flex-start;
  background: transparent; border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 7px;
  color: rgba(230, 249, 255, 0.6); font-size: 0.76rem; padding: 6px 12px; cursor: pointer;
}
.mfc-ops-toggle:hover { color: rgba(230, 249, 255, 0.9); border-color: rgba(var(--nc-primary-rgb), 0.35); }
.mfc-ops-caret { width: 14px; height: 14px; }
</style>
