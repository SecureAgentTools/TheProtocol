/**
 * §MCPTEST30 (V0640): the bundle templates Agent Forge offers are the ones this registry can build (agentvault2-66).
 *
 * The view offered all three templates and fell back to a hard-coded "full-capacity" for a download without a pick,
 * while no frame stood up since 2026-09-07 carries that template's directory: every such download answered 500. The
 * registry lists what it has (GET /onboard/bundle-templates, in its own order: full-capacity, minimal, ppao); the
 * picker shows those in the catalogue's order, and a download without a pick takes the first one the registry listed.
 */

/** The template ids a /onboard/bundle-templates answer lists, or null when the answer carries no list. */
export function listedTemplateIds(body: unknown): string[] | null {
  const ids = (body as { templates?: unknown } | null | undefined)?.templates
  return Array.isArray(ids) ? ids.filter((x): x is string => typeof x === 'string') : null
}

/** The catalogue entries to offer: the listed ones, in catalogue order; the whole catalogue while nothing is listed
 *  (a registry that answers no list, or lists none, keeps the picker as it was rather than empty). */
export function offeredTemplates<T extends { id: string }>(catalogue: readonly T[], listed: string[] | null): T[] {
  if (!listed || listed.length === 0) return [...catalogue]
  return catalogue.filter(t => listed.includes(t.id))
}

/** The template a download without a pick asks for: the first one listed, else "minimal" (every image ships it). */
export function defaultTemplateId(listed: string[] | null): string {
  return listed && listed.length > 0 ? listed[0] : 'minimal'
}

/** Whether a picked template is one this registry lists (an unread list judges nothing). */
export function isOffered(picked: string | null | undefined, listed: string[] | null): boolean {
  return !picked || !listed || listed.length === 0 || listed.includes(picked)
}
