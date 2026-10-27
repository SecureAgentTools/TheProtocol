/**
 * Agent Credentials Storage Service
 *
 * Stores agent credentials in browser localStorage so the user doesn't have
 * to re-paste them on every reload. The `client_secret` IS persisted — this
 * is necessary for `authenticateAsAgent` to re-exchange the secret for a JWT
 * after the agent JWT expires (default 30min) or the user reloads the page.
 *
 * SECURITY TRADEOFF:
 *   Whoever has access to your browser's localStorage for this origin has
 *   access to your agent. We accept this because:
 *     1. You paste the secret into this origin voluntarily.
 *     2. Keeping the secret only in memory means the user has to re-paste
 *        on every reload — which forced users to re-enter or the auth flow
 *        was effectively broken (sandbox bug report 2026-04-23).
 *     3. Secrets never leave the browser except to the auth endpoint of
 *        this origin via `/api/v1/auth/agent/token` (OAuth2 password grant).
 *   If your threat model doesn't tolerate this, rotate the agent secret and
 *   log out to clear localStorage, or use a fresh browser profile.
 *
 * §POCKETBRIDGE #PK32 — THE SEALED VAULT. The trade-off above is no longer the
 * only option: when the Pocket biometric lock seals the vault, this store
 * routes every read/write through `services/credentialVault.ts` — AES-256-GCM
 * at rest, key derived from the lock credential's WebAuthn PRF (or a
 * non-extractable device key where PRF is unavailable), plaintext in memory
 * only while unsealed. Public API unchanged: reads stay synchronous; while the
 * vault is sealed-and-locked they return {} and `isSealedLocked()` says why —
 * a caller must never mistake "locked" for "you own no credentials" (§DIDCHUNK
 * class). Every route that could hit this state stands behind the lock screen.
 */
import { credentialVault } from '@/services/credentialVault'

export interface StoredAgentCredentials {
  did: string
  client_id: string
  client_secret?: string  // PERSISTED to localStorage so re-auth after reload works.
  name?: string
  humanReadableId?: string
  registry?: string
  registry_url?: string
  created_at?: string
  /**
   * §FEFRAME W1 — WHOSE credential this is: the developer id (as a string) that saved or first used it on this
   * origin. A browser shared by two accounts used to offer each one the other's saved agents (the switcher built a row
   * for EVERY stored credential, §agentfinder), which contradicted the logout rationale that kept them. Unset on rows
   * saved before V0502: those stay usable by whoever is logged in and are claimed by the first account that the
   * server confirms owns the agent, or that signs in as it.
   */
  owner_developer_id?: string
  /** §FEFRAME W1 — set when the agent's registry answered 401 to this secret; cleared by the next success. */
  rejected_at?: string
}

/** The developer whose view every read returns (null = no one logged in: only unclaimed legacy rows). */
let currentOwner: string | null = null

class AgentCredentialsStore {
  /** §FEFRAME W1: set by the auth store whenever the logged-in developer changes (null on logout). */
  setCurrentOwner(developerId: string | number | null | undefined): void {
    currentOwner = developerId === null || developerId === undefined || developerId === '' ? null : String(developerId)
  }

  getCurrentOwner(): string | null { return currentOwner }

  /** Every row, whoever owns it. Internal: writes read-modify-write the WHOLE map so other owners' rows survive. */
  private readAll(): Record<string, StoredAgentCredentials> {
    try {
      return credentialVault.getAll() as Record<string, StoredAgentCredentials>
    } catch (error) {
      console.error('Failed to load agent credentials:', error)
      return {}
    }
  }

  private visibleTo(c: StoredAgentCredentials | undefined, owner: string | null): boolean {
    if (!c) return false
    if (!c.owner_developer_id) return true            // legacy, unclaimed: as before V0502
    return owner !== null && c.owner_developer_id === owner
  }

  /**
   * The credentials the logged-in developer may see and use: their own plus unclaimed legacy rows.
   * Sealed-and-locked returns {} — check `isSealedLocked()` before rendering that as "no credentials".
   */
  getAllCredentials(): Record<string, StoredAgentCredentials> {
    const all = this.readAll()
    const out: Record<string, StoredAgentCredentials> = {}
    for (const [did, c] of Object.entries(all)) if (this.visibleTo(c, currentOwner)) out[did] = c
    return out
  }

  /** True when a sealed vault exists and the session key is not in memory. */
  isSealedLocked(): boolean {
    try { return credentialVault.state() === 'sealed-locked' } catch { return false }
  }

  /**
   * Get credentials for a specific agent
   */
  getCredentials(agentDid: string): StoredAgentCredentials | null {
    const c = this.readAll()[agentDid]
    return this.visibleTo(c, currentOwner) ? c : null
  }

  /** Write-through to the vault. Fire-and-forget on purpose: the public API
   *  has always been synchronous and every caller relies on that; an encrypt
   *  failure is logged, and the seal's own self-test protects the migration
   *  moment (the only write whose loss would be unrecoverable). */
  private writeAll(all: Record<string, StoredAgentCredentials>): void {
    void credentialVault.setAll(all).catch((error: unknown) => {
      console.error('Failed to persist agent credentials:', error)
    })
  }

  /**
   * Store credentials for an agent. The secret IS persisted — see file
   * header for the security trade-off rationale (and the sealed-vault upgrade).
   */
  storeCredentials(credentials: StoredAgentCredentials): void {
    try {
      const all = this.readAll()
      all[credentials.did] = {
        ...credentials,
        owner_developer_id: credentials.owner_developer_id || currentOwner || undefined,
        rejected_at: undefined,
        created_at: credentials.created_at || new Date().toISOString()
      }
      this.writeAll(all)
      if (import.meta.env.DEV) console.log(`Stored credentials for agent ${credentials.did} (${credentials.name || 'Unnamed'})`)
    } catch (error) {
      console.error('Failed to store agent credentials:', error)
    }
  }

  /**
   * Store multiple credentials at once. Secrets persist — see file header.
   */
  storeMultipleCredentials(credentialsList: StoredAgentCredentials[]): void {
    try {
      const all = this.readAll()
      credentialsList.forEach(creds => {
        all[creds.did] = {
          ...creds,
          owner_developer_id: creds.owner_developer_id || currentOwner || undefined,
          rejected_at: undefined,
          created_at: creds.created_at || new Date().toISOString()
        }
      })
      this.writeAll(all)
      if (import.meta.env.DEV) console.log(`Stored credentials for ${credentialsList.length} agents`)
    } catch (error) {
      console.error('Failed to store multiple agent credentials:', error)
    }
  }

  /**
   * Remove credentials for an agent
   */
  removeCredentials(agentDid: string): void {
    try {
      const all = this.readAll()
      if (!this.visibleTo(all[agentDid], currentOwner)) return   // never another account's row
      delete all[agentDid]
      this.writeAll(all)
      import.meta.env.DEV && console.log(`Removed credentials for agent ${agentDid}`)
    } catch (error) {
      console.error('Failed to clear agent credentials:', error)
    }
  }

  /**
   * Forget every credential the logged-in developer can see (their own and unclaimed legacy rows); another account's
   * rows on this browser are left alone.
   */
  clearAll(): void {
    try {
      const all = this.readAll()
      for (const did of Object.keys(all)) if (this.visibleTo(all[did], currentOwner)) delete all[did]
      this.writeAll(all)
      import.meta.env.DEV && console.log('Cleared the visible agent credentials')
    } catch (error) {
      console.error('Failed to clear agent credentials:', error)
    }
  }
  
  /**
   * Check if we have credentials for an agent
   */
  hasCredentials(agentDid: string): boolean {
    return !!this.getCredentials(agentDid)
  }

  /**
   * §FEFRAME W1 — stamp the logged-in developer on unclaimed legacy rows for these DIDs (the server just confirmed
   * this developer owns them, or the developer just signed in as one). Rows another account owns are never taken over
   * here. Returns how many rows it stamped.
   */
  claim(dids: Iterable<string>): number {
    if (!currentOwner) return 0
    const all = this.readAll()
    let n = 0
    for (const did of dids) {
      const c = all[did]
      if (c && !c.owner_developer_id) { c.owner_developer_id = currentOwner; n++ }
    }
    if (n) this.writeAll(all)
    return n
  }

  /**
   * §FEFRAME W1 — the logged-in developer's saved credentials in the bulk importer's own shape
   * (services/credImport.ts reads `[{did, client_id, client_secret, name?, registry_url?}]`). A row saved without an
   * address belongs to the console it was saved on, so the file names that origin: it imports correctly anywhere.
   */
  exportVisible(thisOrigin: string): Array<{ did: string; client_id: string; client_secret?: string; name?: string; registry_url: string }> {
    return Object.values(this.getAllCredentials())
      .filter(c => c?.did && c?.client_id && c?.client_secret)
      .map(c => ({
        did: c.did, client_id: c.client_id, client_secret: c.client_secret,
        ...(c.name ? { name: c.name } : {}),
        registry_url: c.registry_url || thisOrigin,
      }))
  }

  /** §FEFRAME W1 — the agent's registry answered 401 to this secret: never auto-retry it; the person re-enters it. */
  markRejected(agentDid: string): void {
    const all = this.readAll()
    const c = all[agentDid]
    if (!c || !this.visibleTo(c, currentOwner)) return
    c.rejected_at = new Date().toISOString()
    this.writeAll(all)
  }

  /** §FEFRAME W1 — a successful sign-in clears an earlier rejection. */
  clearRejected(agentDid: string): void {
    const all = this.readAll()
    const c = all[agentDid]
    if (!c || !c.rejected_at || !this.visibleTo(c, currentOwner)) return
    delete c.rejected_at
    this.writeAll(all)
  }
  
  /**
   * Merge stored credentials with agent data
   */
  mergeWithStoredCredentials(agents: any[]): any[] {
    const storedCredentials = this.getAllCredentials()
    import.meta.env.DEV && console.log('[AgentCredentialsStore] 🔄 MERGE START: Processing', agents.length, 'agents')
    import.meta.env.DEV && console.log('[AgentCredentialsStore] Stored credentials for DIDs:', Object.keys(storedCredentials))
    
    return agents.map(agent => {
      const creds = storedCredentials[agent.did]
      if (creds) {
        import.meta.env.DEV && console.log(`[AgentCredentialsStore] ✅ Found stored credentials for ${agent.did}`)
        return {
          ...agent,
          client_id: creds.client_id,
          client_secret: creds.client_secret,
          name: agent.name || creds.name,
          humanReadableId: agent.humanReadableId || creds.humanReadableId,
          registry: agent.registry || creds.registry,
          registry_url: agent.registry_url || creds.registry_url,
          hasCredentials: true,
          // §FEFRAME W1: a secret its registry refused stays visible (so it can be re-entered or removed) but is
          // never picked automatically
          hasInvalidCredentials: !!creds.rejected_at
        }
      }
      
      // IMPORTANT: Backend doesn't return credentials, so if not in store, they don't have any
      import.meta.env.DEV && console.log(`[AgentCredentialsStore] ⚠️ No credentials found for ${agent.did}`)
      
      // Log if backend sent hasCredentials (it shouldn't!)
      if ('hasCredentials' in agent) {
        import.meta.env.DEV && console.log(`[AgentCredentialsStore] 🔴 DELETING backend's hasCredentials=${agent.hasCredentials} for ${agent.did}`)
      }
      
      // CRITICAL: Clear ANY credentials that might be coming from backend
      // Backend should NEVER return real credentials or credential status
      delete agent.client_id;
      delete agent.client_secret;
      delete agent.hasCredentials;      // CRITICAL: Remove backend's false claim!
      delete agent.hasInvalidCredentials; // Remove this too!
      
      return {
        ...agent,
        // Explicitly set to undefined to clear any values
        client_id: undefined,
        client_secret: undefined,
        hasCredentials: false,  // Now this is the ONLY source of truth
        hasInvalidCredentials: false
      }
    })
  }
}

// Export singleton instance
export const agentCredentialsStore = new AgentCredentialsStore()

/**
 * Initialize test agent credentials
 * DEPRECATED: No longer auto-injects hardcoded credentials.
 * Use the UI "Add Credentials" flow or console helpers instead:
 *   window.addAgentCredentials(did, clientId, clientSecret, name)
 */
export function initializeTestCredentials(): void {
  // No-op: Hardcoded test credentials removed in OWL24 cleanup.
  // Agents are now created via the onboarding flow and credentials
  // should be added through the UI or console helpers.
  import.meta.env.DEV && console.log('[initializeTestCredentials] No-op -- use UI or console helpers to add credentials')
}
