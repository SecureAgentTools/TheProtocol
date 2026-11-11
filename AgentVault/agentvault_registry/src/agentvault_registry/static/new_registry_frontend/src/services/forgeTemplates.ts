/**
 * §MCPTEST30 (V0640): the bundle templates Agent Forge offers are the ones this registry can build (agentvault2-66).
 *
 * The view offered all three templates and fell back to a hard-coded "full-capacity" for a download without a pick,
 * while no frame stood up since 2026-09-07 carries that template's directory: every such download answered 500. The
 * registry lists what it has (GET /onboard/bundle-templates, in its own order); the picker shows those in the
 * catalogue's order, and a download without a pick takes the first one the registry listed.
 *
 * V0658 (b): the catalogue is the starter ("minimal": an external agent on the SDK, Agent Forge's featured default,
 * selected when nothing is picked) and the PPAO orchestrator; "full-capacity" left with Frame A (D6-822).
 */

export interface ForgeTemplate {
  id: 'minimal' | 'ppao'
  icon: string
  tags: string[]
  featured: boolean
  defaultPorts: { mcp: number; agent: number; metrics: number }
  descriptionPlaceholder?: string
}

/** The templates Agent Forge offers, in its order: the featured starter first. */
export const FORGE_TEMPLATES: readonly ForgeTemplate[] = [
  {
    id: 'minimal',
    icon: '⚡',
    tags: ['sdk', 'external', 'a2a', 'payments', 'docker'],
    featured: true,
    defaultPorts: { mcp: 3101, agent: 8055, metrics: 8056 },
    descriptionPlaceholder: 'An agent on my own machine that answers one skill and is paid per call.',
  },
  {
    id: 'ppao',
    icon: '◎',
    tags: ['orchestrator', 'dashboard', 'docker', 'payments', 'mcp', 'claude-desktop'],
    featured: false,
    defaultPorts: { mcp: 3100, agent: 3100, metrics: 3101 },
    descriptionPlaceholder: 'A PPAO orchestrator agent that fans out paid jobs to specialist agents.',
  },
]

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

/** The template a download without a pick asks for, and the one the picker selects for a form that has none: the first
 *  one listed, else "minimal" (the starter, which every image ships). */
export function defaultTemplateId(listed: string[] | null): string {
  return listed && listed.length > 0 ? listed[0] : 'minimal'
}

/** Whether a picked template is one this registry lists (an unread list judges nothing). */
export function isOffered(picked: string | null | undefined, listed: string[] | null): boolean {
  return !picked || !listed || listed.length === 0 || listed.includes(picked)
}

/** Whether the form holds anything the person did: a later step, a name, or a template other than the one the picker
 *  selected for them (the default is no more a choice than the provider name filled in from the profile). */
export function formHasProgress(stepIdx: number, name: string, templateId: string | null | undefined,
                                defaultId: string | null): boolean {
  return stepIdx > 0 || !!name || (!!templateId && templateId !== defaultId)
}
