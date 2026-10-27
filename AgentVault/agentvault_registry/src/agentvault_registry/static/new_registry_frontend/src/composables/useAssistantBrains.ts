import { appLocale } from '@/services/appLocale'
/**
 * composables/useAssistantBrains.ts — §POCKETBRIDGE4 WS-P: ONE assistant
 * machine for the Pocket panel AND the bridge dock. Extracted from
 * PocketAssistant (batch 3) with behavior preserved; every reply still NAMES
 * its brain (S1) and no brain ever confirms money (D5) — doors open confirm
 * screens, the human finishes.
 *
 * `autoOpenDoors` differs by surface: Pocket auto-opens (the phone flow);
 * the desktop dock renders the door button instead — doors lead to Pocket
 * routes, and yanking a desktop bridge user across shells uninvited would be
 * the R3 doors-not-dumps mistake in reverse.
 */
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import apiClient from '@/services/api/client'
import { developerApi } from '@/services/api/developers'
import { exchangeService } from '@/services/api/exchangeService'
import { parseUtterance, CAPABILITY_ENTRIES, exampleIn, type RosterAgent, type VenueSymbol } from '@/services/voice/intentGrammar'
import { useFrames } from '@/composables/useFrames'
import { doorFor, type Door } from '@/services/voice/doors'
import { useI18n } from '@/composables/useI18n'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { getLocale } from '@/i18n'

export type Brain = 'grammar' | 'bridge' | 'byo'

export interface AssistantMsg {
  id: number
  role: 'user' | 'assistant'
  brain?: string
  text: string
  unresolved?: string
  door?: Door | null
  doorLabel?: string
}

const BYO_KEY = 'tp_byok'

/* Local interpolation: the composable resolves its own templates through the
   two-argument t() (fallback guaranteed) and fills them here — never
   t(key, text, params), which returns the fallback verbatim with a literal
   {placeholder} on screen (§BRIDGE R6). */
const interp = (s: string, p: Record<string, any>) =>
  s.replace(/\{(\w+)\}/g, (_, k) => (k in p ? String(p[k]) : `{${k}}`))

export function useAssistantBrains(opts: {
  speak?: (t: string) => void
  onPush?: () => void
  autoOpenDoors?: boolean
} = {}) {
  // tp, never a hand-rolled JS pass over t(): once a key lands in a bundle,
  // vue-i18n compiles the message and renders {slots} empty BEFORE any later
  // pass can fill them — the bug tp() fixed at its root 2026-08-23 (E3's
  // silent empty balance answer was this file's copy of it).
  const { t, tp } = useI18n()
  const router = useRouter()
  const autoOpen = opts.autoOpenDoors !== false
  // D6-835: the units the grammar takes and the examples name: this frame's own first, then its peers'
  const { frames: knownFrames, localCurrency: frameUnit } = useFrames()
  const units = computed(() => Array.from(new Set([frameUnit.value, ...knownFrames.value.map(f => f.currency || '')]
    .filter(Boolean))))
  const speak = (t: string) => { try { opts.speak?.(t) } catch { /* tts optional */ } }

  const brain = ref<Brain>('grammar')
  const status = ref<any>(null)
  const busy = ref(false)
  const msgs = ref<AssistantMsg[]>([])
  let mid = 0
  /* The example COMMAND stays English (the parser only matches English — a
     translated example would not work); only the gloss after the dash moves. */
  // the stake example only where a stake can be opened (registry-config's staking_enabled, as the stake sheet's door;
  // his word 2026-10-25: "staking doesnt exist anymore in the way it did"); D6-835: each example names the frame's unit
  const { config: assistantRegistryCfg } = useRegistryConfig()
  const caps = computed(() => CAPABILITY_ENTRIES
    .filter(c => c.key !== 'stake' || assistantRegistryCfg.value.staking_enabled === true)
    .map(c => `${exampleIn(c.cmd, frameUnit.value)} — ${t('pocket.caps.' + c.key, c.gloss)}`))

  /* Brain names are shown as the message's byline, so they must resolve the
     same way whether the label was stamped on push or read live. */
  const BRAIN_NAMES: Record<Brain, [string, string]> = {
    grammar: ['pocket.assistant.brainGrammar', 'command grammar'],
    bridge: ['pocket.assistant.brainBridge', 'Claude · personal bridge'],
    byo: ['pocket.assistant.brainByo', 'Claude · your API key'],
  }
  const brainName = (b: Brain) => t(BRAIN_NAMES[b][0], BRAIN_NAMES[b][1])

  const brainLabel = computed(() => brainName(brain.value))
  const brainNote = computed(() =>
    brain.value === 'grammar'
      ? t('pocket.assistant.noteGrammar', 'Deterministic commands — instant, free, on-device. No model involved.')
      : brain.value === 'bridge'
        ? t('pocket.assistant.noteBridge', 'Your own Claude Code subscription, via this registry’s admin-only bridge. It can read via tools; only YOU confirm money.')
        : t('pocket.assistant.noteByo', 'Direct to the Anthropic API with your own key, from this browser. It can only talk — doors and confirms stay yours.'))

  /* BYO key — client-side only (D4) */
  const byoKey = ref(localStorage.getItem(BYO_KEY) || '')
  function saveByoKey() { try { localStorage.setItem(BYO_KEY, byoKey.value.trim()) } catch { /* private mode */ } }

  /* grammar context — the roster + venue symbols the app already knows */
  const roster = ref<RosterAgent[]>([])
  const symbols = ref<VenueSymbol[]>([])
  // §FESUITE (V0576): a roster that could not be read is not a roster without that agent ("No agent in your roster
  // matched X" was said about a list never read); it is asked again before the next name is matched
  const rosterFailed = ref(false)
  // the roster read in flight (its first answer can wait on the client's 2 s retry): a question asked meanwhile waits for
  // it rather than matching a name against a roster not read yet (V0576's proof answered "No agent in your roster
  // matched" before the read had settled)
  let ctxLoading: Promise<void> | null = null
  function loadCtx(): Promise<void> {
    const run = readCtx()
    ctxLoading = run
    void run.finally(() => { if (ctxLoading === run) ctxLoading = null }).catch(() => { /* readCtx catches its own */ })
    return run
  }
  async function readCtx() {
    try {
      const { data } = await apiClient.get('/developers/me/agents', { params: { limit: 30, sort: 'balance' } })
      const rows: any[] = data?.agents || data || []
      roster.value = rows.map(a => ({ did: a.did || a.agent_did || '', name: a.name || a.agent_name || a.human_readable_id || '' })).filter(a => a.did)
      rosterFailed.value = false
    } catch { rosterFailed.value = true }
    try {
      const ls = await exchangeService.listings()
      symbols.value = (ls.listings || []).map((l: any) => ({ symbol: l.symbol, name: l.display_name }))
    } catch { /* symbols optional */ }
  }

  async function loadStatus() {
    try { status.value = (await apiClient.get('/assistant/status')).data } catch { status.value = null }
  }

  function push(m: Omit<AssistantMsg, 'id'>) {
    msgs.value.push({ ...m, id: ++mid })
    try { opts.onPush?.() } catch { /* scroll is a nicety */ }
  }

  function openDoor(d: Door) {
    if (!d || d.inPlace) return
    router.push({ path: d.path, query: d.query }).catch(() => {})
  }

  async function answerBalance(agentName?: string) {
    try {
      const s = await developerApi.getTegSummary()
      const total = Number(s.total_balance).toLocaleString(appLocale())
      const liquid = Number(s.total_liquid_balance).toLocaleString(appLocale())
      const staked = Number(s.total_staked_balance).toLocaleString(appLocale())
      return agentName
        ? tp('pocket.assistant.balanceFleetOne', 'I read fleet totals here — for one agent open its card. Fleet: {total} total, {liquid} liquid across {n} agents.',
                 { total, liquid, n: s.agent_count })
        : tp('pocket.assistant.balanceFleet', '{total} total — {liquid} liquid, {staked} locked, across {n} agents.',
                 { total, liquid, staked, n: s.agent_count })
    } catch (e: any) {
      return tp('pocket.assistant.balanceFailed', "Couldn't read balances: {err}",
                    { err: e?.response?.data?.detail || e?.message || t('pocket.common.requestFailed', 'request failed') })
    }
  }

  async function runGrammar(utterance: string) {
    if (ctxLoading) await ctxLoading
    if (rosterFailed.value) await loadCtx()
    const r = parseUtterance(utterance, { roster: roster.value, symbols: symbols.value, units: units.value })
    const unresolved = r.unresolved && rosterFailed.value && r.unresolved.startsWith('No agent in your roster matched')
      ? t('pocket.assistant.rosterUnread', 'Your agents could not be read just now, so no name could be matched against them.')
      : r.unresolved
    const door = doorFor(r.intent)
    let text = r.understood
    if (r.intent.kind === 'balance') {
      text = await answerBalance(r.intent.agent?.name || r.intent.agentQuery)
    } else if (r.intent.kind === 'help') {
      text = t('pocket.assistant.iCan', 'I can:') + ' ' + caps.value.join(' · ')
    }
    push({ role: 'assistant', brain: brainName('grammar'), text, unresolved, door: door && !door.inPlace ? door : null, doorLabel: door && !door.inPlace ? t('pocket.assistant.open', 'Open') : undefined })
    speak(r.intent.kind === 'balance' || r.intent.kind === 'help' ? text : r.understood)
    if (autoOpen && door && !door.inPlace) openDoor(door)
  }

  async function runBridge(utterance: string) {
    try {
      const { data } = await apiClient.post('/assistant/ask', { prompt: utterance })
      const text = data?.reply || t('pocket.assistant.emptyReply', '(empty reply)')
      push({ role: 'assistant', brain: brainName('bridge'), text })
      speak(text.slice(0, 300))
    } catch (e: any) {
      push({ role: 'assistant', brain: brainName('bridge'), text: tp('pocket.assistant.bridgeError', 'Bridge error: {err}', { err: e?.response?.data?.detail || e?.message || t('pocket.common.requestFailed', 'request failed') }) })
    }
  }

  async function runByo(utterance: string) {
    const key = byoKey.value.trim()
    if (!key) {
      push({ role: 'assistant', brain: brainName('byo'), text: t('pocket.assistant.pasteKey', 'Paste an Anthropic API key above first — it stays in this browser.') })
      return
    }
    try {
      const { default: Anthropic } = await import('@anthropic-ai/sdk')
      const client = new Anthropic({ apiKey: key, dangerouslyAllowBrowser: true })
      // max_tokens deliberately short: assistant-panel replies, brevity instructed.
      const resp = await client.messages.create({
        model: 'claude-opus-5',
        max_tokens: 2048,
        system:
          'You are the Pocket assistant inside TheProtocol app (sovereign AI-agent registry: agents, their balances in the unit each frame names, locked units and bonds, THE GUILD work orders, the AGORA market). ' +
          'You have NO tools here — answer from the conversation, keep replies to a few phone-sized sentences, and when the user wants an action, point them at the right Pocket screen (Send, Payments, Trade, Approvals). Never claim to have moved units. ' +
          // §POCKETI18N — the app is localised; a reply in a language the user
          // did not choose is the same gap as an untranslated label.
          `The user's app language is "${getLocale()}" — reply in that language.`,
        messages: [
          ...msgs.value.slice(-10).map(m => ({ role: (m.role === 'user' ? 'user' : 'assistant') as 'user' | 'assistant', content: m.text })),
          { role: 'user' as const, content: utterance },
        ],
      })
      let text = ''
      for (const block of resp.content) if (block.type === 'text') text += block.text
      push({ role: 'assistant', brain: brainName('byo'), text: text || t('pocket.assistant.noText', '(no text in reply)') })
      speak(text.slice(0, 300))
    } catch (e: any) {
      push({ role: 'assistant', brain: brainName('byo'), text: tp('pocket.assistant.apiError', 'Anthropic API error: {err}', { err: `${e?.status ? 'HTTP ' + e.status + ' — ' : ''}${e?.message || t('pocket.common.requestFailed', 'request failed')}` }) })
    }
  }

  async function handle(utterance: string) {
    const u = utterance.trim()
    if (!u || busy.value) return
    push({ role: 'user', text: u })
    busy.value = true
    try {
      if (brain.value === 'grammar') await runGrammar(u)
      else if (brain.value === 'bridge') await runBridge(u)
      else await runByo(u)
    } finally { busy.value = false }
  }

  return { brain, status, busy, msgs, caps, brainLabel, brainNote, byoKey, saveByoKey, loadCtx, loadStatus, handle, openDoor }
}
