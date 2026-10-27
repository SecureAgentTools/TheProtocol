import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import ts from 'typescript'

/**
 * The console's value words (agentvault2-56, 2026-10-23; his words "crop the staked and token words out of the
 * screenshots. better correct it in code" and "go. all nine languages"). The console says LOCKED for what the ledger
 * calls staked (the bonds and locks: the backend's own bond states are locked and matured), UNITS for value, a
 * capability PERMIT for IronKey's L4 credential and a PAYMENT AUTHORIZATION for the A2A payment credential.
 *
 *  - BUNDLES: no string in any of the nine bundles names a stake or a token, except under a key KEPT names: the
 *    staking feature's own screens (behind STAKING_ENABLED, its rates behind STAKING_REWARDS_ENABLED), the frame
 *    switches that are named staking, and the sign-in terms (bootstrap, OAuth, pull and session tokens). Code inside a
 *    string is not a word and is not read: placeholders ({staked}), code spans, API fields (tokens_issued) and ledger
 *    event names (TokensTransferred).
 *  - SOURCES: the same words written straight into a component (its template's text and its script's strings) may
 *    not grow, file by file (SOURCE_CEILING). A file that loses some may lower its ceiling. Published writing with a
 *    review of its own is not counted here: the blog (each post has its wording test), the legal texts and the
 *    blueprint pages. Neither are developer log lines, nor code: a script's strings are read by the TypeScript parser.
 */

const SRC = path.resolve(__dirname, '..')
const LOCALES = ['en', 'de', 'es', 'fr', 'ja', 'ko', 'pt', 'ru', 'zh'] as const
type Loc = typeof LOCALES[number]

const WORDS: Record<Loc, RegExp> = {
  en: /\b(?:un)?stak(?:e|ed|es|er|ers|ing)?\b|\btokens?\b/i,
  // German compounds a word: Zahlungstokens, Inhaber-Token, gestakt
  de: /staking|\bstake|staken|gestakt|token/i,
  es: /\bstak|token/i,
  fr: /\bstak|token|jeton/i,
  pt: /\bstak|token/i,
  ru: /стейк|токен/i,
  ja: /ステーク|トークン/,
  ko: /스테이크|스테이킹|토큰/,
  zh: /质押|代币|令牌/,
}

/** Key prefixes whose strings keep the words, each for its reason. */
const KEPT: string[] = [
  // (agentvault2-69, 2026-10-25, his words "staking doesnt exist anymore in the way it did" and "staking wroding fully
  // gone": the staking feature's own screens, doors and switches say lock, locked units, unlock and payout on locked
  // units now, so none of them keeps a word any more)
  // sign-in terms: bootstrap, OAuth, pull and session tokens are credentials, not value
  'agentBuilderView.nav.acquiringToken', 'agentBuilderView.nav.reacquireToken', 'agentBuilderView.token.',
  'agentForgeView.authSchemes.oauth2.desc', 'agentForgeView.fields.tokenUrl.', 'agentForgeView.steps.deploy.ctaHint',
  'agents.fields.bootstrapToken', 'agents.placeholders.bootstrapToken', 'identity.bootstrapToken',
  'governanceDocsView.ref.intro', 'landingPage.flow.f1.text', 'operatorManagementView.appTable.rotatePullToken',
  'operatorManagementView.docker.desc', 'operatorManagementView.rotatedTokenModal.', 'operatorPortalView.credentials.pullLabel',
  'operatorPortalView.credentials.title', 'pocket.connect.honest1', 'tutorial.topics.a2a-auth.body',
  'tutorial.topics.bootstrap-token.', 'agentDetails.delegatedNote', 'cockpit.ch.noNotes', 'mcpTester.probes.token_scope.',
  // the translation backlog: the English is right, an older translation still spells the formula's fields as words
  'missionControl.cards.supplyInvariantHint',
]

const kept = (key: string) => KEPT.some((p) => key.startsWith(p))

/** A string's words: what is code inside it is left out. */
export function words(s: string): string {
  return s
    .replace(/\{[^{}]*\}/g, ' ')
    .replace(/`[^`]*`/g, ' ')
    .replace(/(^|[\s"'(=>])\/[\w\-.{}:]+(?:\/[\w\-.{}:]*)*/g, '$1 ')
    .replace(/[\p{L}\p{N}]+(?:_[\p{L}\p{N}]+)+/gu, ' ')
    .replace(/\b(?:[A-Z][a-z0-9]+){2,}\b/g, ' ')
}

type Bundle = Record<string, string>

function flat(o: unknown, p = '', out: Bundle = {}): Bundle {
  if (o && typeof o === 'object') {
    for (const [k, v] of Object.entries(o as Record<string, unknown>)) flat(v, p ? `${p}.${k}` : k, out)
  } else if (typeof o === 'string') out[p] = o
  return out
}

const bundles = Object.fromEntries(
  LOCALES.map((l) => [l, flat(JSON.parse(fs.readFileSync(path.join(SRC, 'i18n', 'locales', `${l}.json`), 'utf8')))]),
) as Record<Loc, Bundle>

// ── sources ──────────────────────────────────────────────────────────────────────────────────────────────────────────

const HUMAN_ATTR = /\s(?:title|placeholder|aria-label|alt|label|confirm-text|cancel-text|hint|tooltip|description|subtitle|heading)="([^"]*)"/g
// a bound label (`:title="t('k', 'Fallback')"`) and a mustache (`{{ t('k', 'Fallback') }}`) carry text too: a fallback
// whose key no bundle holds is exactly what renders (agentModal.engage.subFree said "no reputation staked" that way)
const BOUND_HUMAN_ATTR = /\s(?::|v-bind:)(?:title|placeholder|aria-label|alt|label|confirm-text|cancel-text|hint|tooltip|description|subtitle|heading|empty-text|text)="([^"]*)"/g
const MUSTACHE = /\{\{([\s\S]*?)\}\}/g
const unescapeAttr = (v: string) => v.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&')
const TAG = /<(?:"[^"]*"|'[^']*'|[^'">])*>/g

/** The words a person can read in one source file: a template's text and plain attributes, a script's strings. */
export function sourceText(src: string, isVue: boolean): string {
  const out: string[] = []
  let script = src
  if (isVue) {
    const a = src.indexOf('<template')
    const b = src.lastIndexOf('</template>')
    if (a >= 0 && b > a) {
      const raw = src.slice(a, b)
        .replace(/<!--[\s\S]*?-->/g, ' ')
        .replace(/<(code|pre)\b[^>]*>[\s\S]*?<\/\1>/g, ' ')
      // the strings inside mustaches and bound labels, read as code by the parser (their keys and code are not words)
      const exprs = [...raw.matchAll(MUSTACHE)].map((m) => m[1])
      for (const tag of raw.match(TAG) || []) exprs.push(...[...tag.matchAll(BOUND_HUMAN_ATTR)].map((m) => unescapeAttr(m[1])))
      for (const e of exprs) out.push(...humanStrings(`(${e}\n)`))
      const tpl = raw
        .replace(MUSTACHE, ' ')
        .replace(TAG, (tag) => ' ' + [...tag.matchAll(HUMAN_ATTR)].map((m) => m[1]).join(' ') + ' ')
      out.push(tpl)
    }
    script = [...src.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]).join('\n')
  }
  out.push(...humanStrings(script))
  return out.map(words).join('\n')
}

/** The strings in a piece of code a person could read: a sentence, or a label (one capitalised word); never a key, a
 *  path or a header name. */
function humanStrings(code: string): string[] {
  return scriptStrings(code).filter((lit) => /\p{L}{2}/u.test(lit) && !/^[A-Z][\w]*(?:-[A-Z][\w]*)+$/.test(lit)
    && (/\s/.test(lit) || /^[A-Z]/.test(lit)))
}

/** A script's strings as the TypeScript parser reads them: string and template literals, never code or comments, and
 *  not what a log line says. */
function scriptStrings(code: string): string[] {
  const out: string[] = []
  const visit = (n: ts.Node): void => {
    if (ts.isImportDeclaration(n) || ts.isExportDeclaration(n)) return
    if (ts.isCallExpression(n) && ts.isPropertyAccessExpression(n.expression) && ts.isIdentifier(n.expression.expression)
      && ['console', 'log', 'logger'].includes(n.expression.expression.text)) return
    if (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) out.push(n.text)
    else if (ts.isTemplateExpression(n)) out.push([n.head.text, ...n.templateSpans.map((sp) => sp.literal.text)].join(' '))
    ts.forEachChild(n, visit)
  }
  visit(ts.createSourceFile('source.ts', code, ts.ScriptTarget.Latest, false, ts.ScriptKind.TS))
  return out
}

/** Published writing with a review of its own (see the header). */
const NOT_COUNTED = ['views/BlogView.vue', 'content/legal/', 'data/blueprints/']

function sourceFiles(dir: string, acc: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name)
    if (NOT_COUNTED.some((n) => path.relative(SRC, p).startsWith(n.replace(/\/$/, '')))) continue
    if (e.isDirectory()) {
      if (e.name === 'node_modules' || e.name === 'assets') continue
      sourceFiles(p, acc)
    } else if (/\.(vue|ts)$/.test(e.name) && !/\.(test|spec)\.ts$|\.d\.ts$/.test(e.name)) acc.push(p)
  }
  return acc
}

export function countWords(text: string): number {
  return (text.match(new RegExp(WORDS.en.source, 'gi')) || []).length
}

/** Per file, the most the words may appear (2026-10-23, counted again once the guard read mustaches and bound labels; lowered
 *  2026-10-25 to the counts on agentvault2-69's W1 batch 2e, 89194d64: 43 files at none, 14 lower). The sign-in screens hold most
 *  of them. Lower a ceiling when a file loses some; never raise one to let a new word in. */
const SOURCE_CEILING: Record<string, number> = {
  'components/AgentDetailModal.vue': 2,
  'components/ApiTesterDisplay.vue': 8,
  'components/GalacticMapCanvas.vue': 1,
  'components/bridge/BridgeAttention.vue': 1,
  'components/cockpit/PaneChannels.vue': 1,
  'components/command/BalanceReconcileModal.vue': 1,
  'components/command/FleetOverview.vue': 1,
  'components/command/RegistryConsole.vue': 2,
  'components/common/QuickAgentModal.vue': 1,
  'components/landing/ShowcaseChat.vue': 1,
  'components/myagents/PaymentTokensPanel.vue': 1,
  'components/operator/OPAccountTab.vue': 1,
  'components/organizations/AgentAuthorityPanel.vue': 2,
  'components/staking/CrossRegistryTransfer.vue': 1,
  'composables/useTutorialRegistry.ts': 1,
  'services/auth.ts': 1,
  'services/frameKit.ts': 1,
  'services/mcpTester/probeFamilies.ts': 3,
  'services/voice/intentGrammar.ts': 3,
  'stores/sessions.ts': 3,
  'stores/twoFactor.ts': 1,
  'views/A2AProtocolDocs.vue': 21,
  'views/AdminDevelopers.vue': 2,
  'views/AdminMailFleet.vue': 2,
  'views/AgentDetails.vue': 1,
  'views/ComplianceDocs.vue': 1,
  'views/EigenTrustCommand.vue': 1,
  'views/FederationDocs.vue': 2,
  'views/GettingStartedDocs.vue': 5,
  'views/HealthMonitorUltimate.vue': 2,
  'views/NetworkArchitecture.vue': 3,
  'views/OperatorManagement.vue': 6,
  'views/RoadmapView.vue': 1,
  'views/TokenEconomyDocs.vue': 1,
  'views/Tutorials/data/agentCicd.track.ts': 4,
  'views/Tutorials/data/agentLifecycle.track.ts': 15,
  'views/Tutorials/data/agoraTrading.track.ts': 4,
  'views/Tutorials/data/attestationsCompliance.track.ts': 6,
  'views/Tutorials/data/crossRegistryCommerce.track.ts': 10,
  'views/Tutorials/data/disputesTrust.track.ts': 14,
  'views/Tutorials/data/enforcementTrust.track.ts': 8,
  'views/Tutorials/data/federatedSettlements.track.ts': 6,
  'views/Tutorials/data/fullAgentEconomy.track.ts': 4,
  'views/Tutorials/data/organizations.track.ts': 5,
  'views/Tutorials/data/reputationSignals.track.ts': 7,
  'views/Tutorials/data/smartContracts.track.ts': 12,
  'views/Tutorials/data/stakingGovernance.track.ts': 8,
  'views/Tutorials/data/tokenEconomics.track.ts': 33,
  'views/Tutorials/guided/tours/api-keys.tour.ts': 1,
  'views/Tutorials/guided/tours/cockpitDesk.tour.ts': 1,
  'views/Tutorials/guided/tours/forge.tour.ts': 1,
  'views/Tutorials/guided/tours/opEnforcement.tour.ts': 2,
  'views/Tutorials/guided/tours/organizations.tour.ts': 2,
  'views/Tutorials/guided/tours/settings.tour.ts': 1,
  'views/pocket/PocketConnectClaude.vue': 1,
}

describe('the console says locked and units, not staked and tokens', () => {
  it('the gate can see the words, and not the code inside a string', () => {
    for (const s of ['Staked', 'STAKED', 'at stake', 'Unstake', 'capability tokens', 'a token']) expect(WORDS.en.test(words(s)), s).toBe(true)
    for (const s of ['TokensTransferred', 'tokens_issued', '{staked} locked', 'mistake', 'Locked', 'units', 'the `token` field',
      'POST /auth/agent/token'])
      expect(WORDS.en.test(words(s)), s).toBe(false)
    expect(WORDS.de.test(words('Zahlungstokens'))).toBe(true)
    expect(WORDS.de.test(words('Attestierungstakt'))).toBe(false)
    expect(WORDS.zh.test(words('能力令牌已吊销'))).toBe(true)
  })

  it('reads what a person can read in a component, and not its code', () => {
    const vue = [
      `<template><div :title="tokenTitle" class="token-row" @click="stake(token, x => x > 1)">Staked {{ t('k', 'Staked') }}`,
      `<code>token</code><span title="Your tokens">POST /auth/agent/token</span>`,
      `<p :title="t('k.tokenTitle', 'Copy the tokens')">{{ t('k.stakeLine', 'No reputation staked') }} {{ tokenCount }}</p></div></template>`,
      `<script setup lang="ts">`,
      `const token = ref('')`,
      `const label = 'Locked' // the token is a credential`,
      `log.warn('token refresh failed')`,
      'ui.showError(\'Stake failed\', `${n} tokens moved`, \'X-Capability-Token\')',
      `</script>`,
    ].join('\n')
    // the text "Staked" (and its mustache fallback), the title "Your tokens", the bound title's and the mustache's
    // fallbacks, the toast "Stake failed" and "tokens moved"; never a key (k.tokenTitle), a variable or a path
    expect(countWords(sourceText(vue, true))).toBe(7)
  })

  it.each(LOCALES)('%s: no string names a stake or a token outside the kept keys', (loc) => {
    const bad = Object.entries(bundles[loc])
      .filter(([k, v]) => !kept(k) && WORDS[loc].test(words(v)))
      .map(([k, v]) => `${k} = ${v.slice(0, 90)}`)
    expect(bad).toEqual([])
  })

  it('keeps nothing it does not need: every kept prefix still holds a word in some bundle', () => {
    const idle = KEPT.filter((p) => !LOCALES.some((loc) =>
      Object.entries(bundles[loc]).some(([k, v]) => k.startsWith(p) && WORDS[loc].test(words(v)))))
    expect(idle).toEqual([])
  })

  // This walk parses every component and script in the tree, about 4 to 5 s on its own; vitest's 5 s default timed
  // out under a full run on a loaded host (agentvault2-56, 2026-10-23), so the walk names its own limit.
  it('no component writes more of the words than it did', () => {
    const counts: Record<string, number> = {}
    for (const f of sourceFiles(SRC)) {
      const n = countWords(sourceText(fs.readFileSync(f, 'utf8'), f.endsWith('.vue')))
      if (n) counts[path.relative(SRC, f)] = n
    }
    if (process.env.VOCAB_PRINT) console.log(JSON.stringify(counts, Object.keys(counts).sort(), 2))
    const over = Object.entries(counts)
      .filter(([f, n]) => n > (SOURCE_CEILING[f] ?? 0))
      .map(([f, n]) => `${f}: ${n} (ceiling ${SOURCE_CEILING[f] ?? 0})`)
    expect(over).toEqual([])
  }, 60_000)
})

// ── the critical words (§VOCAB widened, agentvault2-aa, 2026-10-25, for V0643) ──────────────────────────────────────────
// His words that day to agentvault2-69: "i dont want the critical wording. only compliant ones" and "i want the illegal
// wording completly gone before opening" (sessionlogs2026/PLAN_2026-10-25_COMPLIANT_OPENING.md lists the words and what
// replaces them: journal 52's guard, plus insurance, APY/APR and tokenomics). English and German are held; the other
// seven bundles fall back to English where they lack a key (the translation backlog). Not critical, as the plan keeps
// them: earning trust, non-profit, the cryptographic words, investigating, a game that someone wins (German "gewinnt"),
// and a bounty (German "Prämie"). "returns" is critical only in its money sense (returns on, annual returns): as a verb
// ("the remainder returns to the client") it is how the console speaks.

const CRITICAL: Record<'en' | 'de', RegExp> = {
  en: new RegExp(['\\b(?:rewards?|rewarded|rewarding|yields?|APY|APR|dividends?|shares|stocks?|IPO|invest(?!igat)\\w*',
    'profits?|revenues?|earn(?:s|ed|ing|ings)?|crypto(?!graph)\\w*|insurance|insured|premiums?|tokenomics|banks?|banking',
    'on-chain|utility tokens?|returns? on|(?:annual|expected|guaranteed|high|investment) returns?)\\b'].join('|'), 'i'),
  de: new RegExp(['\\b(?:belohn\\w*|rendite\\w*|dividende\\w*|aktie\\w*|investi(?!gat)\\w*|gewinn(?:e|s|beteiligung\\w*)?',
    'umsatz\\w*|umsätze\\w*|krypto(?!gra)\\w*|versicher\\w*|banken?|bankwesen|ertr[äa]g\\w*|zinsen|verdien\\w*|apy|ipo',
    'on-chain)\\b'].join('|'), 'i'),
}
const CRITICAL_ALLOW: Record<'en' | 'de', RegExp> = {
  en: /\bearn(?:s|ed|ing)? (?:the |their |its |your )?trust\b|\bnon-profit\b/gi,
  de: /\bVertrauen\b[^.!?]*?\bverdien\w*/gi,
}

/** Key prefixes whose strings keep a critical word today, each for its reason; the list only shrinks. */
const CRITICAL_KEPT: string[] = [
  // compliant statements: the negations the plan keeps (no insurance, zero revenue share)
  'landingPage.sectionB.enfEyebrow', 'landingPage.sectionB.enfH3a', 'operator.pitch.subtitle',
  // the licence's own terms, his and the legal texts' call
  'enterpriseLandingView.topology.point3Text', 'operatorPageView.frames.fineprint',
  // earned marks: reputation from verified work, never money; the wording is W1's (agentvault2-69) to choose
  'discoveryView.filters.earnedMarks', 'pocket.cosmetics.earnedLine', 'pocket.cosmetics.earnedNone',
  // AGORA's words wait for his AGORA call (sessionlogs2026/BACKLOG_2026-09-21_AGORA_VOCABULARY.md)
  'ourstate.stocks.foot',
]
const criticalKept = (key: string) => CRITICAL_KEPT.some((p) => key.startsWith(p))

/** The critical words in a text a person reads (its code already left out by words()). */
export function criticalWords(text: string, loc: 'en' | 'de' = 'en'): string[] {
  const t = words(text).replace(CRITICAL_ALLOW[loc], ' ')
  return t.match(new RegExp(CRITICAL[loc].source, 'gi')) || []
}

/** Per file, the most critical words a component may write today (2026-10-25, counted by this gate); lower a ceiling
 *  when a file loses some, never raise one to let a new word in. */
const SOURCE_CEILING_CRITICAL: Record<string, number> = {
  'components/common/EarnedMarkCollar.vue': 1,
  'components/common/EarnedMarkLegend.vue': 3,
  'components/common/TrackRecordPanel.vue': 2,
  'components/forensics/StuckFundsTab.vue': 1,
  'components/landing/ShowcaseChat.vue': 2,
  'services/bridge/grammar.ts': 1,
  'services/voice/intentGrammar.ts': 1,
  'views/Bridge.vue': 3,
  'views/ComplianceMonitor.vue': 3,
  'views/Discovery.vue': 1,
  'views/FlareShop.vue': 2,
  'views/HealthMonitorUltimate.vue': 1,
  'views/NetworkArchitecture.vue': 1,
  'views/ServicesShowcase.vue': 3,
  'views/TrustReputationDocs.vue': 1,
  'views/Tutorials/data/enforcementTrust.track.ts': 1,
  'views/Tutorials/guided/tours/cockpitDesk.tour.ts': 1,
  'views/Tutorials/guided/tours/discovery.tour.ts': 1,
  'views/Tutorials/guided/tours/disputes.tour.ts': 1,
  'views/Tutorials/guided/tours/reputation.tour.ts': 1,
  'views/pocket/PocketCosmetics.vue': 3,
  'views/pocket/PocketOurStateThread.vue': 1,
}

describe('the console names no critical word: rewards, yield, shares, invest, earn, crypto, insurance', () => {
  it('the gate sees the words, and lets the plan\'s kept senses through', () => {
    for (const s of ['Rewards', 'APY', 'yield', 'dividend', 'shares', 'IPO', 'investors', 'profit', 'revenue', 'Earnings',
      'crypto', 'insurance', 'tokenomics', 'bank', 'on-chain', 'returns on your units', 'annual returns'])
      expect(criticalWords(s).length, s).toBeGreaterThan(0)
    for (const s of ['earn their trust', 'non-profit use', 'cryptographic proof', 'investigating', 'the remainder returns to the client',
      'share this link', 'Locked units', 'learn more', 'the ExchangeSharesIssued event', 'ledger_rewards_total'])
      expect(criticalWords(s), s).toEqual([])
    expect(criticalWords('Die Belohnung', 'de')).toEqual(['Belohnung'])
    for (const s of ['der letzte Agent gewinnt', 'eine Prämie ausschreiben', 'Wie Agenten Vertrauen über Konsens verdienen'])
      expect(criticalWords(s, 'de'), s).toEqual([])
  })

  it.each(['en', 'de'] as const)('%s: no string names a critical word outside the kept keys', (loc) => {
    const bad = Object.entries(bundles[loc])
      .filter(([k, v]) => !criticalKept(k) && criticalWords(v, loc).length)
      .map(([k, v]) => `${k} = ${v.slice(0, 90)}`)
    expect(bad).toEqual([])
  })

  it('keeps nothing it does not need: every critical kept prefix still holds a word in English or German', () => {
    const idle = CRITICAL_KEPT.filter((p) => !(['en', 'de'] as const).some((loc) =>
      Object.entries(bundles[loc]).some(([k, v]) => k.startsWith(p) && criticalWords(v, loc).length)))
    expect(idle).toEqual([])
  })

  it('no component writes more critical words than it did', () => {
    const counts: Record<string, number> = {}
    for (const f of sourceFiles(SRC)) {
      const n = criticalWords(sourceText(fs.readFileSync(f, 'utf8'), f.endsWith('.vue'))).length
      if (n) counts[path.relative(SRC, f)] = n
    }
    if (process.env.VOCAB_PRINT) console.log('CRITICAL ' + JSON.stringify(counts, Object.keys(counts).sort(), 2))
    const over = Object.entries(counts)
      .filter(([f, n]) => n > (SOURCE_CEILING_CRITICAL[f] ?? 0))
      .map(([f, n]) => `${f}: ${n} (ceiling ${SOURCE_CEILING_CRITICAL[f] ?? 0})`)
    expect(over).toEqual([])
  }, 60_000)
})
