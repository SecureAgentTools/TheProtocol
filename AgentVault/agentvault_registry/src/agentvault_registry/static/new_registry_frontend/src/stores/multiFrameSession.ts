/**
 * multiFrameSession — now a FACADE over `commandSessions` (§BRIDGE R10).
 *
 * WHY THIS STOPPED BEING ITS OWN STORE
 * There were two answers to "am I connected to registry X?": this store (the
 * Settings console) and `commandSessions` (Galactic Command, which additionally
 * has refresh-token reconnect, per-DID agent tokens, the vault import and the
 * credential roster). The Commander asked for the vault import to live in
 * SETTINGS — and the moment both surfaces sit in the same place, two stores that
 * can disagree is the §FANOUTFIX mistake with a login attached: you would import
 * a vault in Settings, the console beside it would still say "not connected",
 * and Mission Control would show none of those agents as yours.
 *
 * So `commandSessions` is THE session store and this keeps its old shape for the
 * three call sites that already use it (AdminFx, AdminTreasury, useAdminFrames)
 * — no behaviour change for them, one source of truth for everyone.
 *
 * Persistence is inherited from commandSessions (Commander decision D2): access
 * tokens in memory, refresh tokens in sessionStorage, passwords never stored.
 */
import { defineStore } from 'pinia'
import { computed } from 'vue'
import { useCommandSessions } from './commandSessions'

export interface FrameSession {
  adminToken: string | null
  adminEmail: string | null
  agentToken: string | null
  agentLabel: string | null
  error: string | null
  busy: boolean
  via?: 'direct' | 'relay' | null
  baseUrl?: string | null
}

const blank = (): FrameSession => ({
  adminToken: null, adminEmail: null, agentToken: null, agentLabel: null, error: null, busy: false,
  via: null, baseUrl: null,
})

export const useMultiFrameSession = defineStore('multiFrameSession', () => {
  const cs = useCommandSessions()

  /** Present the shared session in this store's historical shape. */
  function view(frame: string): FrameSession {
    const s = cs.sessionFor(frame)
    if (!s) return blank()
    const active = cs.activeAgentFor(frame)
    return {
      adminToken: s.adminToken,
      adminEmail: s.adminEmail,
      agentToken: active?.token || null,
      agentLabel: active?.did || null,
      error: s.error,
      busy: s.status === 'connecting',
      // §FOREIGNDEV — callers need to know which road the session came in on,
      // because the follow-up calls have to take the same one. Dropping these
      // here is how the agent picker kept relaying after a direct login.
      via: s.via ?? null,
      baseUrl: s.baseUrl ?? null,
    }
  }

  async function connectAdmin(frame: string, email: string, password: string, baseUrl?: string | null): Promise<boolean> {
    // §FOREIGNDEV — the address must travel with the credentials, or the store
    // silently falls back to the admin-only relay and a developer is refused.
    return cs.connectAdmin(frame, email, password, baseUrl)
  }

  /** Agent tokens are keyed by DID in the shared store; a client_id is a stable
   *  stand-in when the caller has not resolved the DID yet. */
  async function connectAgent(frame: string, clientId: string, clientSecret: string, label?: string): Promise<boolean> {
    const did = label && label.startsWith('did:') ? label : clientId
    const tok = await cs.mintAgentToken(frame, clientId, clientSecret, did)
    return !!tok
  }

  function disconnect(frame: string) { cs.disconnect(frame) }
  function disconnectAll() { cs.disconnectAll() }

  const sessionFor = (frame: string) => view(frame)
  const adminTokenFor = (frame: string): string | null => cs.adminTokenFor(frame)
  const agentTokenFor = (frame: string): string | null => cs.activeAgentFor(frame)?.token || null
  const isAdminConnected = (frame: string): boolean => cs.isConnected(frame)
  const isAgentConnected = (frame: string): boolean => !!cs.activeAgentFor(frame)
  /** Historical shape: UPPERCASE single-letter frame keys. */
  const connectedFrames = computed(() =>
    cs.connectedKeys.map(k => (k.length === 1 ? k.toUpperCase() : k)))

  /** Pass-through: the facade must not hide the alias map, or a caller that
   *  speaks target keys can never see a session opened under a directory key. */
  const registerAliases = (pairs: Array<{ key?: string | null; canonical?: string | null }> | null | undefined) =>
    cs.registerAliases(pairs)

  return {
    connectAdmin, connectAgent, disconnect, disconnectAll, registerAliases,
    sessionFor, adminTokenFor, agentTokenFor, isAdminConnected, isAgentConnected, connectedFrames,
  }
})
