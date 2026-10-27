/**
 * The configuration catalog (§FESUITE V0595, his word 2026-10-11: "we need env setup in the application forms ... the
 * env flips that are frame exclusive should be still displayed for operators but greyed out and not chooseable").
 *
 * GET /public/env-catalog answers every setting a registry can choose to run (the server's services/env_catalog.py):
 * its options, its scope (`frame`: an operator sees it greyed with the frame's value and cannot choose it; `operator`:
 * chosen, starting from the frame's value) and this registry's own option (`current`, read from its env:
 * `current_source` says set, default or unknown; an unknown one is never guessed).
 */
import { apiClient } from './client'

export interface EnvCatalogEntry {
  key: string
  group: string
  label: string
  hint: string
  options: string[]
  default: string
  scope: 'frame' | 'operator'
  reason: string | null
  pair: string | null
  env: string
  current: string | null
  current_source: 'set' | 'default' | 'unknown'
}

export interface EnvCatalog {
  catalog_version: number
  role: 'frame' | 'operator'
  groups: string[]
  entries: EnvCatalogEntry[]
}

export async function loadEnvCatalog(): Promise<EnvCatalog> {
  const resp = await apiClient.get<EnvCatalog>('/public/env-catalog')
  const body = resp.data
  if (!body || !Array.isArray(body.entries)) throw new Error('the registry did not answer with its settings')
  return body
}

/** What a setting is on this registry before anyone chooses: its own option, else the catalog's default. */
export function frameValue(entry: EnvCatalogEntry): string {
  return entry.current ?? entry.default
}

/**
 * An operator application's `env_choices`: the operator-scope settings whose chosen option differs from the frame's
 * own. Unchanged ones are left out on purpose: the operator inherits them, so a later change on the frame reaches it.
 */
export function operatorChoices(catalog: EnvCatalog, chosen: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {}
  for (const e of catalog.entries) {
    if (e.scope !== 'operator') continue
    const v = chosen[e.key]
    if (v !== undefined && v !== frameValue(e) && e.options.includes(v)) out[e.key] = v
  }
  return out
}
