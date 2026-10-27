// Galactic Command — per-registry agent credentials: since §FEFRAME W3 (V0504) a VIEW of the one credential vault.
//
// The roster was a second store (localStorage `gcc_agent_roster_v1`, plaintext, never sealed, never owner-scoped,
// never cleared at logout) beside the vault the rest of the console signs agents in from, so an agent imported for the
// command centre was invisible to the agent switcher and the other way round. Now:
//   - rosterFor(key)   = the vault's rows whose home is that registry (its key, or its address in the frame manifest)
//   - addToRoster      = a vault write with the row's home stamped (`registry` and `registry_url`)
//   - the old roster is MIGRATED into the vault once (for the account signed in when it runs) and deleted; rows whose
//     registry this federation no longer has are kept aside in `gcc_agent_roster_v1_unresolved`, never dropped
// Parsing lives in services/credImport.ts (ONE parser); `parseVault`/`parseCredsTsv` remain as thin wrappers for one
// release.
import { agentCredentialsStore, type StoredAgentCredentials } from '@/services/agentCredentialsStore'
import { currentFrameManifest } from '@/composables/useFrameManifest'
import { allEntries, entryByKey, entryByName, type FrameManifest } from '@/services/frameManifest'
import { parseCredentialLines, parseCredentialText } from '@/services/credImport'

export interface RosterEntry {
  did: string
  client_id: string
  client_secret?: string
  name?: string
  added_at?: string
}

const LEGACY_ROSTER = 'gcc_agent_roster_v1'
const UNRESOLVED = 'gcc_agent_roster_v1_unresolved'
const norm = (k: string) => (k || '').toLowerCase()
const originOf = (u?: string | null): string | null => {
  if (!u) return null
  try { return new URL(u).origin.toLowerCase() } catch { return null }
}

/** Where registry `key` lives: `url` null = THIS registry; undefined = not a registry this manifest names. */
export function homeForKey(key: string, m: FrameManifest | null = currentFrameManifest()): { url: string | null } | undefined {
  if (!m) return undefined
  const k = norm(key)
  if (k === 'home' || k === 'local' || k === m.self.key) return { url: null }
  const e = entryByKey(m, k) || entryByName(m, k) || allEntries(m).find(x => norm(x.name) === k)
  if (!e) return undefined
  if (e.key === m.self.key) return { url: null }
  return { url: e.public_url || e.console_url || null }
}

function belongsTo(c: StoredAgentCredentials, key: string, isLocal: boolean, home: string | null): boolean {
  const reg = norm(c.registry || '')
  if (reg && reg === norm(key)) return true
  const o = originOf(c.registry_url)
  if (isLocal) return !c.registry_url || (typeof window !== 'undefined' && o === window.location.origin.toLowerCase())
  return !!home && o === originOf(home)
}

/** The vault's credentials whose home is registry `key` (for the LOCAL key: the rows that name no other registry). */
export function rosterFor(registryKey: string, isLocal = false): RosterEntry[] {
  migrateRoster()
  const home = isLocal ? null : (homeForKey(registryKey)?.url || null)
  return Object.values(agentCredentialsStore.getAllCredentials())
    .filter(c => belongsTo(c, registryKey, isLocal, home))
    .map(c => ({ did: c.did, client_id: c.client_id, client_secret: c.client_secret, name: c.name, added_at: c.created_at }))
}

export function addToRoster(registryKey: string, entry: RosterEntry, isLocal = false) {
  const home = isLocal ? { url: null } : homeForKey(registryKey)
  agentCredentialsStore.storeCredentials({
    did: entry.did, client_id: entry.client_id, client_secret: entry.client_secret, name: entry.name,
    registry: isLocal ? undefined : norm(registryKey),
    registry_url: home?.url || undefined,
  })
}

export function removeFromRoster(_registryKey: string, did: string) {
  agentCredentialsStore.removeCredentials(did)
}

export function rosterCounts(): Record<string, number> {
  const out: Record<string, number> = {}
  for (const c of Object.values(agentCredentialsStore.getAllCredentials())) {
    const k = norm(c.registry || '') || (c.registry_url ? (originOf(c.registry_url) || 'unknown') : 'local')
    out[k] = (out[k] || 0) + 1
  }
  return out
}

/**
 * Move the old roster into the vault, once. Runs when the frame manifest is known (a key resolves against it) and the
 * vault is readable (not sealed and locked). A row already in the vault is left as the vault has it. Rows whose
 * registry this federation does not name are kept aside, never dropped. Returns what it did (null = not now).
 */
export function migrateRoster(): { moved: number; kept_aside: number } | null {
  let raw: string | null = null
  try { raw = localStorage.getItem(LEGACY_ROSTER) } catch { return null }
  if (!raw) return null
  const m = currentFrameManifest()
  if (!m || agentCredentialsStore.isSealedLocked()) return null
  let roster: Record<string, Record<string, RosterEntry>> = {}
  try { roster = JSON.parse(raw) || {} } catch { roster = {} }
  let moved = 0
  const aside: Record<string, Record<string, RosterEntry>> = {}
  for (const [key, rows] of Object.entries(roster)) {
    const home = homeForKey(key, m)
    for (const e of Object.values(rows || {})) {
      if (!e?.did || !e.client_id) continue
      if (home === undefined) { (aside[key] ||= {})[e.did] = e; continue }
      if (agentCredentialsStore.getCredentials(e.did)) continue
      agentCredentialsStore.storeCredentials({
        did: e.did, client_id: e.client_id, client_secret: e.client_secret, name: e.name,
        registry: home.url ? norm(key) : undefined, registry_url: home.url || undefined,
      })
      moved++
    }
  }
  try {
    if (Object.keys(aside).length) {
      const prev = JSON.parse(localStorage.getItem(UNRESOLVED) || '{}') || {}
      localStorage.setItem(UNRESOLVED, JSON.stringify({ ...prev, ...aside }))
    }
    localStorage.removeItem(LEGACY_ROSTER)
  } catch { /* storage blocked: the next run tries again (writes are idempotent) */ }
  const kept = Object.values(aside).reduce((n, r) => n + Object.keys(r).length, 0)
  return { moved, kept_aside: kept }
}

// ── the old file formats: wrappers over the ONE parser (services/credImport.ts) for one release ─────────────────────
export interface VaultFile {
  version: 1
  registries: Record<string, {
    developer?: { email: string; password?: string }
    agents?: Array<{ did: string; client_id: string; client_secret?: string; name?: string }>
  }>
}

export function parseCredsTsv(text: string): VaultFile {
  const out: VaultFile = { version: 1, registries: {} }
  for (const d of parseCredentialLines(text)) {
    if (d.registry_key && d.password) out.registries[d.registry_key] = { developer: { email: d.email, password: d.password } }
  }
  return out
}

export function parseVault(text: string): VaultFile {
  const doc = parseCredentialText(text)
  if (doc.format === 'unreadable') throw new Error(doc.errors[0] || 'unreadable')
  const out: VaultFile = { version: 1, registries: {} }
  for (const d of doc.developers) {
    const k = d.registry_key || d.registry_url || 'unknown'
    out.registries[k] = { ...(out.registries[k] || {}), developer: { email: d.email, password: d.password } }
  }
  for (const e of doc.entries) {
    const k = e.registry_key || e.registry_url || 'local'
    const r = (out.registries[k] ||= {})
    ;(r.agents ||= []).push({ did: e.did, client_id: e.client_id, client_secret: e.client_secret, name: e.name })
  }
  return out
}
