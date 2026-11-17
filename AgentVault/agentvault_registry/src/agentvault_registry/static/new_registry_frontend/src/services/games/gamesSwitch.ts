/**
 * V0666 the games switch (order gwo_a01c49ec). The registry says GAMES_ENABLED in
 * /api/v1/public/registry-config as games_enabled. Games are on by default, so only an explicit false closes them: a
 * registry that does not say (or a config that could not be read) keeps every game door as it was.
 */
export const GAME_ROUTE_PATHS = ['/games', '/arena', '/tower-defense', '/snake-arena', '/trading'] as const

export function gamesClosed(cfg: Record<string, unknown> | null | undefined): boolean {
  return cfg?.games_enabled === false
}

/**
 * The games' state for a game view's door. A config the registry ANSWERED decides: an explicit false is off, anything
 * else (true, or an older registry that does not say) is on. A config that could not be read is UNKNOWN, never on: no
 * game view mounts and nothing is fetched until the registry has said (V0666 console proof: a failed read resolved to {},
 * {} read as on, and ArenaView fetched /api/v1/arena/* from a registry whose games were off).
 */
export function gamesState(cfg: Record<string, unknown> | null | undefined, readOk: boolean): 'on' | 'off' | 'unknown' {
  if (cfg?.games_enabled === false) return 'off'
  if (!readOk) return 'unknown'
  return 'on'
}

/** Where Try again returns: the game view asked for when it is one (a path, never a URL), else the games hub. */
export function gameReturnPath(to: unknown): string {
  if (typeof to !== 'string' || !to.startsWith('/') || to.startsWith('//')) return '/games'
  const path = to.split(/[?#]/)[0]
  return (GAME_ROUTE_PATHS as readonly string[]).includes(path) ? to : '/games'
}
