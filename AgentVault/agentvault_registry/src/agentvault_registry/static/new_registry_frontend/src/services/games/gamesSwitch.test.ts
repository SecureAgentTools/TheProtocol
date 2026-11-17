/**
 * V0666 the games switch (order gwo_a01c49ec): one flag turns off the game routes, tools and console views together.
 * The registry-config's games_enabled decides the console's game doors:
 *  - false: the sidebar's Game Arena entry is hidden, and a typed URL to any of the five game views (/games, /arena,
 *    /tower-defense, /snake-arena, /trading) lands on one plain page that says the games are off on this registry;
 *  - true, or a registry that does not say (an older one, or a config that could not be read): everything as before.
 *    Games are on by default, so only an explicit false closes them (never "unknown means off").
 * Red before V0666: gamesSwitch.ts, the route meta and the games-off page do not exist.
 */
import { describe, expect, it } from 'vitest'
import { GAME_ROUTE_PATHS, gamesClosed, gamesState, gameReturnPath } from './gamesSwitch'
import { navItemState, type NavCtx } from '../nav/navAccess'
import { NAV_ITEMS } from '../nav/navTable'
import routerSrc from '@/router/index.ts?raw'
import gamesOffSrc from '@/views/GamesOff.vue?raw'
import en from '@/i18n/locales/en.json'

describe('the games switch', () => {
  it('closes only on an explicit false', () => {
    expect(gamesClosed({ games_enabled: false })).toBe(true)
    expect(gamesClosed({ games_enabled: true })).toBe(false)
    expect(gamesClosed({})).toBe(false)
    expect(gamesClosed(null)).toBe(false)
    expect(gamesClosed(undefined)).toBe(false)
  })

  it('an unread config is unknown, never on: no game view mounts until the registry has said', () => {
    // V0666 console proof (sbx-beta, recovery_sweep_member): a registry-config read that failed resolved to {}, {} read as
    // "games on", ArenaView mounted and fetched /api/v1/arena/* from a registry whose games are off (404)
    expect(gamesState({ games_enabled: true }, true)).toBe('on')
    expect(gamesState({}, true)).toBe('on')                          // a registry that does not say (older): on
    expect(gamesState({ games_enabled: false }, true)).toBe('off')
    expect(gamesState({ games_enabled: false }, false)).toBe('off')  // a kept good answer
    expect(gamesState({}, false)).toBe('unknown')
    expect(gamesState(null, false)).toBe('unknown')
    expect(gamesState({ games_enabled: true }, false)).toBe('unknown')
  })

  it('Try again returns only to a game view', () => {
    expect(gameReturnPath('/arena')).toBe('/arena')
    expect(gameReturnPath('/snake-arena?x=1')).toBe('/snake-arena?x=1')
    expect(gameReturnPath('/games')).toBe('/games')
    expect(gameReturnPath('/admin/treasury')).toBe('/games')
    expect(gameReturnPath('https://evil.example/arena')).toBe('/games')
    expect(gameReturnPath('//evil.example/arena')).toBe('/games')
    expect(gameReturnPath(undefined)).toBe('/games')
    expect(gameReturnPath(['/arena'] as unknown as string)).toBe('/games')
  })

  it('names the five game views', () => {
    expect([...GAME_ROUTE_PATHS].sort()).toEqual(['/arena', '/games', '/snake-arena', '/tower-defense', '/trading'])
  })

  it('every game route carries the switch and the guard reads it', () => {
    for (const p of GAME_ROUTE_PATHS) {
      const name = p.slice(1)
      const at = routerSrc.indexOf(`name: '${name}',`)
      expect(at, name).toBeGreaterThan(0)
      const block = routerSrc.slice(at, routerSrc.indexOf('}', routerSrc.indexOf('meta:', at)) + 1)
      expect(block, name).toContain("closedWhenRegistryFlagFalse: 'games_enabled'")
    }
    expect(routerSrc).toContain('gamesState(')
    expect(routerSrc).toContain('loadRegistryConfig(true)')   // one fresh read when the first did not answer
    expect(routerSrc).toContain("unknown: '1'")
    expect(routerSrc).toContain("name: 'games-off'")
  })

  it('the sidebar entry hides where the registry says false, and only there', () => {
    const item: any = NAV_ITEMS.find((i: any) => i.path === '/games')
    expect(item).toBeTruthy()
    expect(item.hiddenWhenRegistryFlagFalse).toBe('games_enabled')
    const rule = { public: false, admin: false, flag: null } as any
    const ctx = (cfg: Record<string, unknown>): NavCtx => ({
      signedIn: true, legacyAdmin: false, flags: [], hasAgent: true, isMainframe: true, fiatEnabled: true,
      registryCfg: cfg, flareTier: null,
    } as NavCtx)
    expect(navItemState(item, rule, ctx({ games_enabled: false }))).toBe('hide')
    expect(navItemState(item, rule, ctx({ games_enabled: true }))).not.toBe('hide')
    expect(navItemState(item, rule, ctx({}))).not.toBe('hide')
  })

  it('the games-off page says one plain sentence, through i18n', () => {
    expect(gamesOffSrc).toContain("t('gamesOff.body'")
    expect((en as any).gamesOff.body).toMatch(/games are off on this registry/i)
  })

  it('an unread config gets its own sentence and a Try again, never "the games are off"', () => {
    expect(gamesOffSrc).toContain("t('gamesOff.unknown'")
    expect(gamesOffSrc).toContain("t('gamesOff.retry'")
    expect(gamesOffSrc).toContain('loadRegistryConfig(true)')
    expect(gamesOffSrc).toContain('gameReturnPath(')
    expect((en as any).gamesOff.unknown).toMatch(/could not be read/i)
    expect((en as any).gamesOff.retry).toMatch(/try again/i)
  })
})
