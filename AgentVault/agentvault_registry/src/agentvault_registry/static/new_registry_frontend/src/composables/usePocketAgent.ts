/**
 * composables/usePocketAgent.ts — §POCKETBRIDGE #PK3.
 *
 * ONE agent-context brain for the Pocket surface. Before this, the identical
 * `credAgents` computed and `ensureAgent()` pair were copy-pasted four times
 * (Send / Stake / Trade / Earn) — the §FANOUTFIX two-copies class, waiting for
 * one copy to learn something the others never hear about. The sealed vault
 * (#PK32) is exactly that lesson arriving: "no credentials" and "credentials
 * sealed and locked" are different answers, and four copies would each have
 * needed the distinction separately.
 */
import { computed, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import { credentialVault } from '@/services/credentialVault'

/**
 * §POCKETCREDS — the vault is a plain object, so a computed over
 * `getAllCredentials()` has ZERO reactive dependencies: Vue evaluates it once
 * and caches it forever (the §BRIDGE R11 computed-over-nothing class). That
 * was latent while credentials only ever changed on desktop surfaces that
 * refetch anyway; the pocket import/adopt flows write credentials UNDER a
 * mounted picker, so the bridge below makes every consumer re-read: the vault
 * bumps its version on open/close/write, and this module-level ref turns that
 * bump into a dependency. Subscribed once per module load, deliberately never
 * unsubscribed (the vault and this module share the app's lifetime).
 */
const vaultRev = ref(0)
try { credentialVault.onChange(() => { vaultRev.value++ }) } catch { /* vault unavailable — reads still work, statically */ }

export interface CredAgent {
  did: string
  name?: string
  client_id: string
  client_secret: string
  registry_url?: string
  /** V0641: an agent you own on this registry with no secret saved in this browser, which the console signs in through
   *  your session (the store's canActAs and owner rail, §FEFRAME W3); its client_id and client_secret are empty */
  viaSession?: boolean
}

export function usePocketAgent() {
  const auth = useAuthStore()

  /**
   * Agents this browser can ACT as: a saved secret (stored, mintable credentials), or, since V0641, an agent you own on
   * this registry, which the console signs in through your session with no secret (viaSession: the store's canActAs,
   * as the header and the picker have since 2026-10-10). Pocket and the buy door asked only the first, so a member on a
   * second device, or whose agents were made over the API, read "No agent with stored credentials yet" on every one of
   * them while the header acted as that member's own agent (agentvault2-5b, 2026-10-25: the console suite's first
   * purchase, fes-20261025T100011Z-490f on sbx-alpha). A saved secret is listed first and wins for its agent.
   */
  const credAgents = computed<CredAgent[]>(() => {
    void vaultRev.value // reactive dependency on the vault's version bump
    let saved: CredAgent[] = []
    try {
      const stored = agentCredentialsStore.getAllCredentials() || {}
      saved = Object.values(stored)
        .filter((a: any) => a?.client_id && a?.client_secret)
        .map((a: any) => ({
          did: a.did || a.agent_did,
          name: a.name,
          client_id: a.client_id,
          client_secret: a.client_secret,
          registry_url: a.registry_url,
        }))
        .filter((a: any) => a.did)
    } catch { saved = [] }
    const seen = new Set(saved.map(a => a.did))
    const owned: CredAgent[] = []
    try {
      for (const row of ((auth as any).availableAgents || []) as any[]) {
        const did = String(row?.did || '')
        if (!did || seen.has(did) || (row.client_id && row.client_secret)) continue
        if (!(auth as any).canActAs?.(row)) continue   // not yours here, or revoked or suspended (services/agentActable)
        owned.push({ did, name: row.name, client_id: '', client_secret: '', registry_url: row.registry_url, viaSession: true })
        seen.add(did)
      }
    } catch { /* the store's list unread: the saved secrets alone */ }
    return [...saved, ...owned]
  })

  /** Sign in as one listed agent: a saved secret through it, an agent you own here through your session (the store's
   *  own row, which carries what its owner rail needs). */
  async function signIn(a: CredAgent): Promise<boolean> {
    if (!a.viaSession) return await (auth as any).authenticateAsAgent(a)
    const row = ((auth as any).availableAgents || []).find((r: any) => r?.did === a.did)
    return row ? await (auth as any).authenticateAsAgent(row) : false
  }

  /** #PK32 — an empty list while the vault is sealed-and-locked is NOT "you
   *  own no agents". Consumers render this reason instead of the zero-state. */
  const sealedLocked = computed<boolean>(() => {
    void vaultRev.value // same bridge: lock/unlock must re-evaluate this
    try { return agentCredentialsStore.isSealedLocked() } catch { return false }
  })

  /** Why an agent action is unavailable right now — null when one is. */
  const noAgentReason = computed<string | null>(() => {
    if (credAgents.value.length) return null
    // the store already acts as an agent (signed in elsewhere in this console): an action here runs as it
    if ((auth as any).activeAgent?.did && (auth as any).agentToken) return null
    return sealedLocked.value
      ? 'Agent credentials are sealed — unlock Pocket with your fingerprint to use them.'
      : 'No agent with stored credentials yet — open the agent switcher (your name in the header) to create or import one.'
  })

  /**
   * V0641 (agentvault2-66's review of be05537f): several agents you own can act here through your session, none is
   * chosen, and no secret is saved: restoreActing does not choose for the member, so a door that acts as THE acting
   * agent (the buy door) must ask for a choice instead of calling with no agent's token (a 401). Screens with an
   * agent select of their own choose visibly and do not read this.
   */
  const chooseReason = computed<string | null>(() => {
    if ((auth as any).activeAgent?.did && (auth as any).agentToken) return null
    const list = credAgents.value
    if (list.some(a => !a.viaSession) || list.length < 2) return null   // a saved secret, or one agent: restoreActing takes it
    let savedId = ''
    try { savedId = localStorage.getItem('activeAgentId') || '' } catch { /* storage unavailable */ }
    if (savedId && list.some(a => a.did === savedId)) return null       // the saved choice is taken
    return 'Several of your agents can act here: choose one in the agent switcher (your name in the header).'
  })

  /**
   * Authenticate as the agent holding `did` (mint/reuse its JWT and make it
   * the store's acting agent). The exact semantics of the four inlined copies.
   */
  async function ensureAgentFor(did: string | null | undefined): Promise<boolean> {
    if (!did) return false
    const a = credAgents.value.find(x => x.did === did)
    if (!a) return false
    if ((auth as any).activeAgent?.did === a.did && (auth as any).agentToken) return true
    return await signIn(a)
  }

  /**
   * Best-effort: make SOME agent the acting one, so surfaces that read
   * `authStore.activeAgent` (quick actions, NEEDS YOU) are live on arrival.
   * Preference order: the store's already-active agent → the persisted
   * `activeAgentId` choice → the first credentialed agent. Never throws; a
   * false return means the surfaces stay blocked and say why.
   * An agent you own here with no saved secret (viaSession) is chosen on its own only as the saved choice or as the
   * only agent that can act: with several, the console does not choose for the member (the store's rule since
   * 2026-10-10), so the surfaces ask instead.
   */
  async function restoreActing(): Promise<boolean> {
    try {
      if ((auth as any).activeAgent?.did && (auth as any).agentToken) return true
      const list = credAgents.value
      if (!list.length) return false
      let preferred: CredAgent | undefined
      try {
        const savedId = localStorage.getItem('activeAgentId')
        if (savedId) preferred = list.find(a => a.did === savedId || (!!a.client_id && a.client_id === savedId))
      } catch { /* storage unavailable */ }
      const target = preferred || list.find(a => !a.viaSession) || (list.length === 1 ? list[0] : undefined)
      if (!target) return false
      return await signIn(target)
    } catch { return false }
  }

  return { credAgents, sealedLocked, noAgentReason, chooseReason, ensureAgentFor, restoreActing }
}
