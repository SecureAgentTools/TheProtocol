/**
 * uiMode.test.ts — §POCKETBRIDGE #PK23 (D2 ratified).
 * The whole entry decision in one pure function: a saved MANUAL choice always
 * beats the width heuristic; the heuristic acts on the fact alone; garbage in
 * storage is ignored, never guessed at.
 */
import { describe, it, expect } from 'vitest'
import { resolveHomeRoute, PHONE_MAX_WIDTH, isPocketMode } from './uiMode'

describe('resolveHomeRoute', () => {
  it('a phone with no saved choice enters Pocket', () => {
    expect(resolveHomeRoute(null, 390)).toBe('/pocket/home')
    expect(resolveHomeRoute(null, PHONE_MAX_WIDTH - 1)).toBe('/pocket/home')
  })

  it('a desktop with no saved choice enters the bridge', () => {
    expect(resolveHomeRoute(null, PHONE_MAX_WIDTH)).toBe('/mission-control')
    expect(resolveHomeRoute(null, 1280)).toBe('/mission-control')
  })

  it('a saved "advanced" beats the phone heuristic — the LITEBRIDGE rule', () => {
    expect(resolveHomeRoute('advanced', 390)).toBe('/mission-control')
  })

  it('a saved "pocket" beats the desktop heuristic', () => {
    expect(resolveHomeRoute('pocket', 1920)).toBe('/pocket/home')
  })

  it('garbage in storage is ignored, not guessed at', () => {
    expect(resolveHomeRoute('banana', 390)).toBe('/pocket/home')
    expect(resolveHomeRoute('banana', 1280)).toBe('/mission-control')
    expect(resolveHomeRoute('', 1280)).toBe('/mission-control')
  })
})

import { resolveDoor as _resolveDoor } from './uiMode'
describe('§PHONESTART resolveDoor — the doors follow the landing decision', () => {
  it('a phone with no saved choice is sent to Pocket doors', () => {
    expect(_resolveDoor('funding', null, 390)).toBe('/pocket/home?fund=1')
    expect(_resolveDoor('agents', null, 390)).toBe('/pocket/agents')
  })
  it('a desktop with no saved choice is sent to the desktop doors', () => {
    expect(_resolveDoor('funding', null, 1440)).toBe('/my-agents?fund=1')
    expect(_resolveDoor('agents', null, 1440)).toBe('/my-agents')
  })
  it('a saved choice beats the width, both ways', () => {
    expect(_resolveDoor('funding', 'advanced', 390)).toBe('/my-agents?fund=1')
    expect(_resolveDoor('agents', 'pocket', 1440)).toBe('/pocket/agents')
  })
})

describe('isPocketMode (§PHONEWORDS) — the sentence about "where things are" agrees with where the doors lead', () => {
  it('follows the saved mode when there is one', () => {
    expect(isPocketMode('pocket', 1440)).toBe(true)
    expect(isPocketMode('advanced', 393)).toBe(false)
  })
  it('falls back to the viewport when nothing is saved, like resolveDoor', () => {
    expect(isPocketMode(null, 393)).toBe(true)
    expect(isPocketMode(null, 1440)).toBe(false)
  })
})

