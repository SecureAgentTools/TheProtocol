/**
 * W4 phase 1 (agentvault2-aa, 2026-10-25): the console reads a ledger event under its old and its new name.
 *
 * The map is the registry's (agentvault_registry/core/ledger_names.py), data for data; every screen that compares an event
 * type against an old name, or keys a table by one, asks the map (the scan below), so the day an emitter writes
 * UnitsTransferred (phase 2) nothing on screen goes blind: the globe draws it, the pocket names it, the health monitor
 * counts it among the locks, mission control counts it, the bridge narrates it, the forensics policy tab protects it.
 */
import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { AGORA_RENAMED, LEGACY, RENAMED, expandLive, labelName, liveNames, liveOld } from './ledgerNames'
import { ledgerEventLabel } from './ledgerEventLabel'
import { BALANCE_MOVING_EVENT_TYPES } from './api/forensics'
import { classifyEventType } from './bridge/grammar'

const SRC = path.resolve(__dirname, '..')

describe('the ledger names, old and new, read as one', () => {
  it('is the registry map, data for data', () => {
    expect(RENAMED).toEqual({
      TokensTransferred: 'UnitsTransferred', TokensIssued: 'UnitsIssued', TokensStaked: 'UnitsLocked',
      TokensUnstaked: 'UnitsUnlocked', StakeForceUnstaked: 'LockForceUnlocked',
      RewardsDistributed: 'LockPayoutsDistributed', RewardsAutoCompounded: 'LockPayoutsRelocked',
      RewardsAutoCompoundSkipped: 'LockPayoutRelockSkipped', TokensBridgeLocked: 'UnitsBridgeLocked',
      TokensBridgeUnlocked: 'UnitsBridgeUnlocked',
    })
    expect(AGORA_RENAMED).toEqual({
      ExchangeDividendDeclared: 'ExchangeDistributionDeclared', ExchangeDividendPaid: 'ExchangeDistributionPaid',
      ExchangeSharesIssued: 'ExchangePointsIssued', ExchangeSharesSplit: 'ExchangePointsSplit',
      ExchangeShareRefloated: 'ExchangePointsRefloated',
    })
    expect(LEGACY).toEqual({ TokenTransferred: 'TokensTransferred', RewardDistributed: 'RewardsDistributed',
      StakeRewardDistributed: 'RewardsDistributed' })
    // the registry's copy, where this checkout holds it
    const reg = path.resolve(SRC, '../../../core/ledger_names.py')
    if (fs.existsSync(reg)) {
      const py = fs.readFileSync(reg, 'utf8')
      for (const [o, n] of Object.entries({ ...RENAMED, ...AGORA_RENAMED, ...LEGACY })) expect(py).toContain(`"${o}": "${n}"`)
    }
  })

  it('reads a new name as its old one, and leaves every other name as it is', () => {
    expect(liveOld('UnitsTransferred')).toBe('TokensTransferred')
    expect(liveOld('TokensTransferred')).toBe('TokensTransferred')
    expect(liveOld('TokenTransferred')).toBe('TokenTransferred')
    expect(liveOld('ExchangeDistributionPaid')).toBe('ExchangeDividendPaid')
    expect(liveOld(undefined)).toBe('')
    expect(liveNames('UnitsLocked')).toEqual(['TokensStaked', 'UnitsLocked'])
    expect(liveNames('AgentCreated')).toEqual(['AgentCreated'])
    expect([...expandLive(['TokensIssued', 'AgentCreated'])].sort()).toEqual(['AgentCreated', 'TokensIssued', 'UnitsIssued'])
  })

  it('labels a renamed event in its new words under either name, AGORA\'s included', () => {
    expect(labelName('RewardsDistributed')).toBe('LockPayoutsDistributed')
    expect(labelName('LockPayoutsDistributed')).toBe('LockPayoutsDistributed')
    expect(labelName('ExchangeDividendPaid')).toBe('ExchangeDistributionPaid')
    expect(labelName('ExchangePointsIssued')).toBe('ExchangePointsIssued')
    for (const [o, n] of [['ExchangeDividendPaid', 'Exchange distribution paid'], ['ExchangeSharesIssued', 'Exchange points issued'],
      ['ExchangeShareRefloated', 'Exchange points refloated']]) {
      expect(ledgerEventLabel(o)).toBe(n)
      expect(ledgerEventLabel(AGORA_RENAMED[o])).toBe(n)
    }
    for (const [o, n] of [['RewardsDistributed', 'Lock payouts distributed'], ['RewardsAutoCompounded', 'Lock payouts relocked'],
      ['TokensTransferred', 'Units transferred'], ['TokensStaked', 'Units locked'], ['StakeForceUnstaked', 'Lock force unlocked']]) {
      expect(ledgerEventLabel(o)).toBe(n)
      expect(ledgerEventLabel(RENAMED[o])).toBe(n)
    }
  })

  it('protects and draws an event under its new name as under its old', () => {
    for (const o of ['TokensIssued', 'TokensTransferred', 'TokensStaked', 'TokensUnstaked', 'RewardsAutoCompounded']) {
      expect(BALANCE_MOVING_EVENT_TYPES.has(o) && BALANCE_MOVING_EVENT_TYPES.has(RENAMED[o])).toBe(true)
      expect(classifyEventType(RENAMED[o])).toBe(classifyEventType(o))
    }
    expect(BALANCE_MOVING_EVENT_TYPES.has('TokenTransferred')).toBe(false)
  })

  it('every screen that names an old event in its code asks the map', () => {
    const OLD = [...Object.keys(RENAMED), ...Object.keys(AGORA_RENAMED)]
    // a quoted name, an object key, or a property read (b.TokensStaked)
    const USE = new RegExp(String.raw`(['"\x60](${OLD.join('|')})['"\x60])|(^\s*(${OLD.join('|')})\s*:)|(\.(${OLD.join('|')})\b)`, 'm')
    // prose that only shows a name to a reader (docs, the journal, tutorials, a test fixture) and the raw ledger explorer
    const PROSE = new Set(['views/BlogView.vue', 'views/TokenEconomyDocs.vue', 'views/GettingStartedDocs.vue', 'views/FederationDocs.vue',
      'views/AdminCanaries.vue', 'views/GalacticCommand.vue', 'views/AdminEvents.vue', 'services/bridge/__fixtures__/realEnvelopes.ts',
      'views/Tutorials/data/agoraTrading.track.ts', 'services/ledgerNames.ts'])
    const files: string[] = []
    const walk = (d: string) => {
      for (const e of fs.readdirSync(d, { withFileTypes: true })) {
        const p = path.join(d, e.name)
        if (e.isDirectory()) { if (e.name !== 'locales' && e.name !== 'node_modules') walk(p) }
        else if (/\.(ts|vue)$/.test(e.name) && !/\.(test|spec)\.ts$/.test(e.name)) files.push(p)
      }
    }
    walk(SRC)
    const users = files.filter((f) => USE.test(fs.readFileSync(f, 'utf8'))).map((f) => path.relative(SRC, f))
    const bad = users.filter((f) => !PROSE.has(f) && !/from '(@\/services|\.|\.\.)\/ledgerNames'/.test(fs.readFileSync(path.join(SRC, f), 'utf8')))
    expect(users.length, 'the scan sees the screens that read the names').toBeGreaterThanOrEqual(9)
    expect(bad, 'read the event under every name it may be written under (services/ledgerNames.ts)').toEqual([])
  })
})
