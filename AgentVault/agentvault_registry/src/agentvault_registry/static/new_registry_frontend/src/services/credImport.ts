/**
 * services/credImport.ts — §POCKETCREDS (2026-08-23).
 *
 * THE one credential-import brain. The parsing, validation and classification
 * that decides which pasted/attached credentials are importable lived inline in
 * `BulkCredentialsImportModal.vue` (desktop); the pocket import sheet is its
 * second consumer, and a second copy is where the two would learn different
 * opinions about which shapes are legal (§FANOUTFIX class). Both surfaces now
 * import from here; this file is PURE (no Vue, no store, no network) so it is
 * node-unit-testable — the caller supplies `hasExisting` for the
 * new-vs-overwrite split.
 *
 * The accepted top-level shapes:
 *   1. `[ {did, client_id, client_secret, ...}, ... ]`   — array of entries
 *   2. `{ did, client_id, ... }`                         — a single entry
 *   3. `{ "<did>": {client_id, ...}, ... }`              — DID-keyed map
 *   §FEFRAME W3 (V0504) — ONE parser for every credential file the console has ever produced:
 *   4. `{ "<registry name>": [ {...}, ... ], ... }`      — entries grouped by registry (the entries' home)
 *   5. the Galactic Command vault, v1 `{version:1, registries:{<key>:{developer?, agents?}}}` and the v2 this console
 *      now exports `{version:2, registries:[{key,name,url,developer?}], agents:[{..., registry_url}]}`
 *   6. credential LINES `key<TAB>url<TAB>email<TAB>password` (the URL column is kept: it is the registry's address)
 *   and the field spellings other screens printed: `agent_did`/`child_did` for `did`, `new_client_secret` for
 *   `client_secret` (a credential reset), `host` for `registry_url`. Developer lines are returned separately
 *   (`parseCredentialText`): a password is used once to sign in at that registry and is never stored.
 */

export interface ParsedCredEntry {
  did: string
  client_id: string
  client_secret: string
  name?: string
  registry_url?: string
  kind: 'new' | 'overwrite' | 'invalid'
  error?: string
}

export const MAX_IMPORT_ENTRIES = 2000

/** One entry with the field spellings other screens printed mapped onto the importer's own (§FEFRAME W3). A home
 *  given by the container (a vault's registry key, a by-registry group) is kept unless the entry names its own. */
export function aliasEntry(e: any, home?: { registry_key?: string | null; registry_url?: string | null }): any {
  if (!e || typeof e !== 'object') return e
  const out: any = { ...e }
  if (!out.did && typeof e.agent_did === 'string') out.did = e.agent_did
  if (!out.did && typeof e.child_did === 'string') out.did = e.child_did
  if (!out.client_secret && typeof e.new_client_secret === 'string') out.client_secret = e.new_client_secret
  if (!out.registry_url && typeof e.host === 'string' && e.host.trim()) {
    const h = e.host.trim()
    out.registry_url = /^https?:\/\//i.test(h) ? h : `https://${h}`
  }
  if (!out.registry_url && home?.registry_url) out.registry_url = home.registry_url
  if (!out.registry_key && !out.registry_url && home?.registry_key) out.registry_key = home.registry_key
  return out
}

const looksLikeEntry = (v: any): boolean =>
  !!v && typeof v === 'object' && !Array.isArray(v) &&
  (('did' in v || 'agent_did' in v || 'child_did' in v) && 'client_id' in v)

/** Normalize ONE parsed JSON document into a flat array of entry objects (every accepted shape). */
export function normalizeEntries(raw: any): any[] | null {
  if (Array.isArray(raw)) return raw.map(e => aliasEntry(e))
  if (!raw || typeof raw !== 'object') return null
  if (looksLikeEntry(raw)) return [aliasEntry(raw)]
  // a Galactic Command vault: its agents, each with the registry it was filed under
  if (raw.registries && typeof raw.registries === 'object') return vaultAgents(raw)
  const keys = Object.keys(raw)
  // entries grouped by registry: every value an array, and no key a DID
  if (keys.length && keys.every(k => Array.isArray(raw[k]) && !/^did:/.test(k))) {
    return keys.flatMap(k => (raw[k] as any[]).map(e => aliasEntry(e, { registry_key: k })))
  }
  return Object.entries(raw).map(([did, body]: [string, any]) => aliasEntry({ did, ...(body || {}) }))
}

function vaultAgents(raw: any): any[] {
  if (Array.isArray(raw.agents)) return raw.agents.map((a: any) => aliasEntry(a))            // v2
  const out: any[] = []
  for (const [key, spec] of Object.entries<any>(raw.registries || {})) {                    // v1
    for (const a of (spec?.agents || [])) out.push(aliasEntry(a, { registry_key: key, registry_url: spec?.url || null }))
  }
  return out
}

export function isValidDid(s: unknown): s is string {
  return typeof s === 'string' && /^did:[a-z0-9]+:.+/.test(s)
}
export function isValidClientId(s: unknown): s is string {
  return typeof s === 'string' && s.length > 0 && s.length < 256
}
export function isValidClientSecret(s: unknown): s is string {
  return typeof s === 'string' && s.length >= 16 && s.length < 1024
}

/**
 * Classify normalized entries into new / overwrite / invalid, with the
 * per-entry reason spelled out. A malformed registry_url is REJECTED, never
 * silently dropped: a credential that quietly falls back to this origin would
 * 401 later with no clue why.
 */
/** Where a registry key from a file lives: `url` null = THIS registry; `ok` false = no registry of this federation. */
export type HomeAnswer = { ok: true; url: string | null } | { ok: false; reason: string }

/** True for an address no other browser can reach: a loopback, `0.0.0.0`, a bare container name. */
export function isLoopbackUrl(u: string): boolean {
  try {
    const h = new URL(u).hostname.toLowerCase()
    return h === 'localhost' || h === '0.0.0.0' || h === '::1' || h === '[::1]' || /^127\./.test(h) || !h.includes('.')
  } catch { return false }
}

export function classifyEntries(
  entries: any[],
  hasExisting: (did: string) => boolean,
  resolveHome?: (registryKey: string) => HomeAnswer,
): ParsedCredEntry[] {
  const out: ParsedCredEntry[] = []
  for (const entry of entries) {
    if (!entry || typeof entry !== 'object') {
      out.push({ did: '?', client_id: '', client_secret: '', kind: 'invalid', error: 'Not an object' })
      continue
    }
    const did = entry.did
    const cid = entry.client_id
    const sec = entry.client_secret
    const name = entry.name
    let regUrl = typeof entry.registry_url === 'string' ? entry.registry_url.trim() : undefined

    const errs: string[] = []
    if (!isValidDid(did)) errs.push('DID invalid (must start with "did:")')
    if (!isValidClientId(cid)) errs.push('client_id missing or invalid')
    if (!isValidClientSecret(sec)) errs.push('client_secret missing or too short')
    if (regUrl) {
      try {
        const u = new URL(regUrl)
        if (isLoopbackUrl(regUrl)) errs.push(`registry_url ${u.host} is a loopback or container address: it names no registry another browser can reach`)
        else if (u.protocol !== 'https:') errs.push('registry_url must be https')
      } catch { errs.push('registry_url is not a URL') }
    } else if (typeof entry.registry_key === 'string' && entry.registry_key && resolveHome) {
      // §FEFRAME W3: a key from a vault or a by-registry file is resolved against the frame manifest
      const home = resolveHome(entry.registry_key)
      if (!home.ok) errs.push(home.reason)
      else regUrl = home.url || undefined
    }

    if (errs.length) {
      out.push({
        did: did || '(missing)', client_id: cid || '', client_secret: sec || '',
        name, registry_url: regUrl, kind: 'invalid', error: errs.join('; '),
      })
      continue
    }
    out.push({
      did, client_id: cid, client_secret: sec, name, registry_url: regUrl,
      kind: hasExisting(did) ? 'overwrite' : 'new',
    })
  }
  return out
}

export interface DocReportRow { name: string; count: number; error?: string }

/**
 * Merge SEVERAL already-read documents (file name + text) into one entry list.
 * The three rules the desktop importer earned (§MULTIFILE): never concatenate
 * TEXT (each doc parses alone), one bad doc never sinks the batch, and a DID
 * in two docs dedupes last-doc-wins with the count REPORTED, not swallowed.
 */
export function mergeCredDocs(docs: { name: string; text: string }[]): {
  entries: any[]
  report: DocReportRow[]
  dupes: number
} {
  const report: DocReportRow[] = []
  const merged = new Map<string, any>()
  const keyless: any[] = []
  let dupes = 0
  for (const d of docs) {
    let doc: any
    try { doc = JSON.parse(d.text) } catch (e: any) {
      report.push({ name: d.name, count: 0, error: `invalid JSON: ${e?.message || 'parse error'}` })
      continue
    }
    const entries = normalizeEntries(doc)
    if (!entries) {
      report.push({ name: d.name, count: 0, error: 'not a credential object or array' })
      continue
    }
    for (const e of entries) {
      const did = e && typeof e === 'object' ? (e as any).did : undefined
      if (typeof did === 'string' && did) {
        if (merged.has(did)) dupes++
        merged.set(did, e)
      } else {
        keyless.push(e) // kept so classify flags it as invalid instead of vanishing it
      }
    }
    report.push({ name: d.name, count: entries.length })
  }
  return { entries: [...merged.values(), ...keyless], report, dupes }
}


// ── §FEFRAME W3 (V0504): the whole text, credential lines included ────────────────────────────────────────────────

export interface ImportDeveloper {
  registry_key: string | null
  registry_url: string | null
  email: string
  /** absent in an export (passwords are never stored): such a line names the registry and needs a sign-in */
  password?: string
}

export interface ImportDocument {
  format: 'vault-v1' | 'vault-v2' | 'lines' | 'entries' | 'unreadable'
  entries: any[]
  developers: ImportDeveloper[]
  errors: string[]
}

/** Credential LINES: `key<TAB>url<TAB>email<TAB>password`, `#` comments. The URL column is the registry's address and
 *  is kept (it used to be thrown away, leaving only a key the console had to guess). */
export function parseCredentialLines(text: string): ImportDeveloper[] {
  const out: ImportDeveloper[] = []
  for (const raw of String(text).split(/\r?\n/)) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const cols = line.split(/\t+|\s{2,}/).map(c => c.trim()).filter(Boolean)
    if (cols.length < 3) continue
    const key = cols[0].toLowerCase()
    const url = cols.find((c, i) => i > 0 && /^https?:\/\//i.test(c)) || null
    const emailIdx = cols.findIndex((c, i) => i > 0 && c.includes('@') && !/^https?:\/\//i.test(c))
    if (emailIdx < 0 || emailIdx === cols.length - 1) continue   // no email, or no password after it
    out.push({ registry_key: key || null, registry_url: url ? url.replace(/\/+$/, '') : null,
      email: cols[emailIdx], password: cols[emailIdx + 1] })
  }
  return out
}

/** ONE entry point for a pasted or attached text: every shape this console ever produced. */
export function parseCredentialText(text: string): ImportDocument {
  const t = String(text || '').trim()
  if (!t) return { format: 'unreadable', entries: [], developers: [], errors: ['empty'] }
  if (!t.startsWith('{') && !t.startsWith('[')) {
    const developers = parseCredentialLines(t)
    return developers.length
      ? { format: 'lines', entries: [], developers, errors: [] }
      : { format: 'unreadable', entries: [], developers: [], errors: ['Expected JSON, or lines of: key<TAB>url<TAB>email<TAB>password'] }
  }
  let raw: any
  try { raw = JSON.parse(t) } catch (e: any) {
    return { format: 'unreadable', entries: [], developers: [], errors: [`invalid JSON: ${e?.message || 'parse error'}`] }
  }
  if (raw && typeof raw === 'object' && !Array.isArray(raw) && raw.registries && typeof raw.registries === 'object') {
    const developers: ImportDeveloper[] = []
    if (Array.isArray(raw.registries)) {                                    // v2
      for (const r of raw.registries) {
        if (r?.developer?.email) developers.push({ registry_key: r.key || r.name || null, registry_url: r.url || null,
          email: r.developer.email, password: r.developer.password })
      }
      return { format: 'vault-v2', entries: vaultAgents(raw), developers, errors: [] }
    }
    for (const [key, spec] of Object.entries<any>(raw.registries)) {          // v1
      if (spec?.developer?.email) developers.push({ registry_key: key, registry_url: spec.url || null,
        email: spec.developer.email, password: spec.developer.password })
    }
    return { format: 'vault-v1', entries: vaultAgents(raw), developers, errors: [] }
  }
  const entries = normalizeEntries(raw)
  return entries
    ? { format: 'entries', entries, developers: [], errors: [] }
    : { format: 'unreadable', entries: [], developers: [], errors: ['not a credential object or array'] }
}

/** The export, in the importer's own shape (vault v2): registries by URL, agents with their `registry_url`. Developer
 *  passwords are never stored, so never exported; a client secret only when asked. */
export function exportVaultV2(
  rows: Array<{ did: string; client_id: string; client_secret?: string; name?: string; registry_url?: string; registry?: string }>,
  registries: Array<{ key: string; name?: string; url: string | null; email?: string | null }>,
  includeSecrets: boolean,
): any {
  return {
    version: 2,
    exported_at: new Date().toISOString(),
    registries: registries.map(r => ({ key: r.key, name: r.name || r.key, url: r.url,
      ...(r.email ? { developer: { email: r.email } } : {}) })),
    agents: rows.map(r => ({ did: r.did, client_id: r.client_id, name: r.name, registry_url: r.registry_url || null,
      ...(r.registry && !r.registry_url ? { registry_key: r.registry } : {}),
      ...(includeSecrets && r.client_secret ? { client_secret: r.client_secret } : {}) })),
  }
}
