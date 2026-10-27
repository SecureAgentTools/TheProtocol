/**
 * Stands in for elkjs (REVIEW_2026-09-30_LICENSING.md, F10).
 *
 * elkjs is EPL-2.0 and does not name the GPL as an EPL "Secondary License", so its code cannot ship inside this
 * AGPL-3.0 frontend without blocking everyone downstream from passing the kit on. mermaid imports elkjs only from the
 * chunk that implements its optional "elk" layout, and no diagram in this code base asks for that layout. Vite's alias
 * (vite.config.ts) points both import specifiers here: a diagram that asks for layout "elk" fails with the message
 * below, and every other diagram keeps rendering with mermaid's default layout.
 */
const REFUSAL = 'The elk layout is not part of this build (elkjs is EPL-2.0); remove "layout: elk" to use the default layout.'

export default class ELK {
  layout(): Promise<never> {
    return Promise.reject(new Error(REFUSAL))
  }

  knownLayoutAlgorithms(): Promise<never[]> {
    return Promise.resolve([])
  }

  knownLayoutOptions(): Promise<never[]> {
    return Promise.resolve([])
  }

  knownLayoutCategories(): Promise<never[]> {
    return Promise.resolve([])
  }

  terminateWorker(): void {}
}
