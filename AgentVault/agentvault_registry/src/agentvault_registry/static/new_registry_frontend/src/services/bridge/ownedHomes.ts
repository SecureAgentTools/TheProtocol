/**
 * §OWNEDHOMES (2026-08-21) — which of your agents get drawn, and WHERE.
 *
 * THE DEFECT, in his words: *"i need all the owned agents displayed ... orbiting
 * their registries"*, against a bridge that showed agents around exactly five of
 * the sixteen registries he is signed in to.
 *
 * Three walls stood between "I own it" and "it is on the stage", and only the
 * first had been found:
 *
 *   W1  The star candidates were built from the LOCAL stores. An agent owned as
 *       a DEVELOPER on another registry arrives from the fan-out as a bare DID
 *       and was never a candidate at all.
 *   W2  Bucketing used `registryUrl`, which only exists on agents you hold a
 *       CREDENTIAL for — it is copied off the credential, not off the registry.
 *       So foreign agents that did get through were filed under LOCAL, and the
 *       quota spread a set that claimed to be one registry.
 *   W3  The stage treats the chosen DIDs as a FILTER over `/agents/locations/`,
 *       which is a SAMPLE. Measured on frame-c: 1,689 of his 4,440 owned agents
 *       were in it (38%), and not one agent he owns elsewhere was.
 *
 * W3 is what actually produced "five registries": the five were where his
 * ownership and the sample happened to intersect. Nothing had failed to load.
 *
 * This module answers both questions in one pass, purely, so the answer can be
 * tested against the real shape of his account instead of inferred from a
 * screenshot.
 */
import { allocateStars, type StarCandidate } from './starQuota'

export interface DirectoryLike {
  key: string
  name?: string | null
  trustDomain?: string | null
  /** Every other spelling the relay accepts for this registry. */
  names?: string[]
}

export interface OwnedAgentRow { did: string; name?: string | null; registryUrl?: string | null }

export interface StarPlanInput {
  /** This registry's own key in the directory namespace. */
  localKey: string
  /** How many individual stars the stage may draw. Geometry is not free. */
  cap: number
  /** Agents you hold credentials for — first claim on each registry's slots. */
  credentialed?: OwnedAgentRow[]
  /** Agents this registry lists for you (names known). */
  localAgents?: OwnedAgentRow[]
  /** Every DID you own HERE. */
  localDids?: string[]
  /** Every DID you own elsewhere, with the registry key it came back from. */
  foreign?: Array<{ did: string; key?: string | null }>
  directory?: DirectoryLike[]
  /** `window.location.origin`, so "is this URL foreign?" is answerable purely. */
  localOrigin?: string
}

/** What the stage needs to place one star. No `names` and not `local` = nowhere. */
export interface StarHome {
  did: string
  name?: string | null
  local?: boolean
  names?: string[]
  trustDomain?: string | null
}

export interface StarPlan {
  chosen: string[]
  homes: StarHome[]
  /** Candidates whose registry this bridge could not name. Counted, never guessed. */
  unplaced: number
  /** How many distinct registries the drawn stars actually cover. */
  registries: number
}

const norm = (x: unknown) => String(x ?? '').toLowerCase().replace(/[^a-z0-9]/g, '')

/** Directory key for a credential URL, or null when we cannot name the host.
 *  Host LABEL first: a renamed operator keeps its original host forever
 *  (op-losangeles answers for singapore), which is what the directory keys it by. */
export function directoryKeyForUrl(url: string | null | undefined, directory: DirectoryLike[]): string | null {
  if (!url) return null
  let host = ''
  // `hostname`, not `host`: the latter carries the port, so a dev credential
  // on http://localhost:8101 produced the label 'localhost:8101' and matched
  // no directory entry. Found by a test written for publicDirectory.hostLabel.
  try { host = new URL(String(url)).hostname } catch { return null }
  if (!host) return null
  const want = norm(host.split('.')[0])
  if (!want) return null
  for (const e of directory) {
    if (norm(e.key) === want) return e.key
    if ((e.names || []).some(m => norm(m) === want)) return e.key
    if (norm(e.name) === want) return e.key
  }
  return null
}

/**
 * Directory entry for a home key.
 *
 * ⚠ THE KEY IS NOT ALWAYS THE DIRECTORY KEY. `/admin/peer/targets` calls the
 * mainframes 'A' and 'B' (with `canonical: 'registry-a'` alongside), while the
 * directory keys them 'registry-a' and 'frame-b' — so after a RELOAD, when
 * sessions are restored from peer targets rather than a vault import, every
 * Registry-A agent would have come back with a home nothing could name and
 * silently gone undrawn. Match the key, then every alias the entry declares.
 */
function metaFor(key: string, directory: DirectoryLike[]): { names: string[]; trustDomain: string | null } | null {
  const want = norm(key)
  const e = directory.find(x => x.key === key)
    || directory.find(x => norm(x.key) === want)
    || directory.find(x => norm(x.name) === want)
    || directory.find(x => (x.names || []).some(m => norm(m) === want))
  if (!e) return null
  const names = [...new Set([e.key, e.name, ...(e.names || [])].filter(Boolean).map(String))]
  if (!names.length) return null
  return { names, trustDomain: e.trustDomain ?? null }
}

export function buildStarPlan(input: StarPlanInput): StarPlan {
  const directory = input.directory || []
  const localKey = input.localKey || '__local__'
  const cap = input.cap
  const origin = input.localOrigin || ''

  const cands: StarCandidate[] = []
  const meta = new Map<string, StarHome>()
  const names = new Map<string, string>()
  const pushed = new Set<string>()
  let unplaced = 0

  for (const a of input.credentialed || []) if (a?.did && a.name) names.set(String(a.did), String(a.name))
  for (const a of input.localAgents || []) if (a?.did && a.name && !names.has(String(a.did))) names.set(String(a.did), String(a.name))

  /*
   * `kind` is not decoration. 'local' and 'foreign' are CLAIMS about where an
   * agent lives; 'unknown' is the absence of one, and collapsing it into
   * 'local' is how a berlin agent ends up orbiting frame-c. A wrong star is
   * worse than a missing one: you cannot falsify it by looking at it.
   */
  const add = (didRaw: unknown, home: string, kind: 'local' | 'foreign' | 'unknown') => {
    const did = didRaw ? String(didRaw) : ''
    if (!did || pushed.has(did)) return
    pushed.add(did)
    cands.push({ did, home })
    if (kind === 'local') { meta.set(did, { did, local: true }); return }
    const m = kind === 'foreign' ? metaFor(home, directory) : null
    if (m) meta.set(did, { did, ...m })
    else { meta.set(did, { did }); unplaced++ }
  }

  // Credentials first: inside a registry's slots, the agents he can ACT as win.
  for (const a of input.credentialed || []) {
    const url = a?.registryUrl
    let foreign = false
    if (url) { try { foreign = new URL(String(url)).origin !== origin } catch { foreign = false } }
    if (!foreign) { add(a?.did, localKey, 'local'); continue }
    const k = directoryKeyForUrl(url, directory)
    if (k && k !== localKey) add(a?.did, k, 'foreign')
    else if (k) add(a?.did, localKey, 'local')
    else {
      let host = String(url)
      try { host = new URL(String(url)).host } catch { /* keep the raw string */ }
      add(a?.did, host, 'unknown')      // own bucket: never steals a local slot
    }
  }
  for (const a of input.localAgents || []) add(a?.did, localKey, 'local')
  for (const d of input.localDids || []) add(d, localKey, 'local')
  for (const f of input.foreign || []) {
    const k = f?.key
    if (!k) { add(f?.did, '__unnamed__', 'unknown'); continue }
    add(f?.did, k, k === localKey ? 'local' : 'foreign')
  }

  /**
   * §STARCAP — the FLOOR is what makes a bigger cap reach the operators.
   * His reason for 1000 was "40 sim agents x 16 registries": with the old
   * floor of 8, cap 1000 sends the surplus almost entirely to the local
   * registry (4,448 local vs ~40 per operator) and operators only move 9 -> 15.
   * A floor of 40 guarantees each registry can show the fleet he actually
   * keeps there. It self-limits: allocateStars clamps the floor to
   * `cap / registries`, so a smaller cap quietly gets a smaller floor.
   */
  const chosen = cands.length ? allocateStars(cands, cap, 40) : []
  const pick = new Set(chosen)
  const homes = chosen.map(did => {
    const m = meta.get(did) || { did }
    const nm = names.get(did)
    return nm ? { ...m, name: nm } : m
  })
  const covered = new Set<string>()
  for (const h of homes) {
    if (h.local) covered.add(localKey)
    else if (h.names && h.names.length) covered.add(h.names[0])
  }
  void pick
  return { chosen, homes, unplaced, registries: covered.size }
}
