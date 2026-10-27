/**
 * §BLOGSHOTS — ONE REGISTRY, TWO SPELLINGS.
 *
 * `/admin/peer/targets` calls the mainframes 'A' and 'B'. The registry
 * directory calls them 'registry-a' and 'frame-b'. A vault import opens
 * sessions under the DIRECTORY key; the Multi-Frame Console asks by TARGET key.
 * The two never met, so the console printed "15 connected" in its summary line
 * while the Frame A and Frame B cards directly underneath both read
 * NOT CONNECTED. Caught in a screenshot taken for a blog post, which is a
 * humbling place to find a bug.
 *
 * Pure on purpose: the store that uses this cannot be unit-tested in this repo
 * (no DOM environment), and an alias table that decides whether you are logged
 * in is not something to leave unproven.
 */

export const normKey = (s: unknown): string => String(s ?? '').trim().toLowerCase()

/** alias -> canonical, from whatever the targets endpoint declared. */
export function buildAliasMap(
  pairs: Array<{ key?: string | null; canonical?: string | null }> | null | undefined,
  base: Record<string, string> = {},
): Record<string, string> {
  const out = { ...base }
  if (!pairs || !Array.isArray(pairs)) return out
  for (const t of pairs) {
    const a = normKey(t?.key), c = normKey(t?.canonical)
    if (a && c && a !== c) out[a] = c
  }
  return out
}

/**
 * The key under which a session for `key` actually lives.
 *
 * Both directions: the caller may hold the letter and the session the canonical
 * name, or the reverse. Returns the normalised input when nothing holds one, so
 * a caller can still write to it.
 */
export function resolveSessionKey(
  key: string,
  has: (k: string) => boolean,
  aliases: Record<string, string>,
): string {
  const k = normKey(key)
  if (has(k)) return k
  const canon = aliases[k]
  if (canon && has(canon)) return canon
  for (const [alias, c] of Object.entries(aliases)) {
    if (c === k && has(alias)) return alias
  }
  return k
}
