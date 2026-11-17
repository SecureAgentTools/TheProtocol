// V0662 (order gwo_16d8fb21303f269406eb772f, his suggestion 4): copy a link to an order, an agent, a blueprint step.
//
// A link that carries a person names the console they typed, never an API base (CLAUDE.md: sessions are per host;
// core/public_url's rule on the registry side): this page's origin and path, then the console's hash route.

export interface ConsoleLocation { origin: string; pathname: string }

export function consoleLink(route: string, loc: ConsoleLocation = window.location): string {
  const r = route.startsWith('/') ? route : `/${route}`
  return `${loc.origin}${loc.pathname || '/'}#${r}`
}
