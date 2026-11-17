// V0667 the public pages readable without JavaScript (order gwo_a9f121caa4138ec9b369814c; his approval, room seq 5381). For EVERY route a
// signed-out visitor reaches (the census is the app's own router: pages.test.ts), one decision: a static page at a plain path, or a reason.
// A page's text always comes from the app's own view and en.json (staticPages/render.ts); this table only says which views, where, and two
// phrases each that the render test looks for.
import { LEGAL_SUITE_V2 } from '@/content/legal/suiteV2'
import { COMPLIANCE_DOCS } from '@/content/complianceDocs'

export const APEX = 'https://theprotocol.cloud'

export interface Instance {
  params: Record<string, string>
  phrases: string[]            // two phrases the page's source renders
  minText: number              // the least text a reader without JavaScript must get
  absent?: string[]            // live data that must never reach the static page (its region is marked data-static="omit")
}

export interface StaticPage {
  route: string                // the app's route path
  instances: Instance[]        // one per parameter value (a route without parameters has one, with no params)
  paths: string[]              // their plain paths
  legal?: boolean              // a legal text: reviewed on its own (the value-word rule does not apply)
}

/** Paths the apex already serves otherwise (CLAUDE.md, the apex rules): a static page never takes one. */
export const RESERVED = ['/api/', '/assets/', '/static/', '/.well-known/', '/blog/', '/blueprints/', '/docs', '/redoc', '/openapi.json',
  '/mcp/', '/ws/', '/ui', '/ui/', '/directory/', '/push-sw.js', '/sitemap.xml', '/robots.txt', '/ppaoshowcase']

/** '/compliance' -> '/compliance/'; '/legal/:page' with {page: 'terms'} -> '/legal/terms/'; an optional parameter left out is dropped. */
export function plainPath(route: string, params: Record<string, string> = {}): string {
  const filled = route.replace(/\/:([A-Za-z]+)\??/g, (_m, n) => (params[n] ? `/${params[n]}` : ''))
  return filled === '/' || filled === '' ? '/' : `${filled.replace(/\/+$/, '')}/`
}

/** The page's live counterpart in the app (hash routes). */
export function liveLink(route: string, params: Record<string, string> = {}): string {
  const filled = route.replace(/\/:([A-Za-z]+)\??/g, (_m, n) => (params[n] ? `/${params[n]}` : ''))
  return `${APEX}/#${filled || '/'}`
}

const one = (phrases: string[], minText: number, absent?: string[]): Instance[] => [{ params: {}, phrases, minText, ...(absent ? { absent } : {}) }]

const TABLE: Omit<StaticPage, 'paths'>[] = [
  { route: '/', instances: one(['The operating system for autonomous agents', 'A five-pillar distributed system'], 3000, ['SERVICES LIVE', 'EVENTS ON LEDGER']) },
  { route: '/a2a-protocol', instances: one(['Agent-to-Agent Protocol', 'JSON-RPC 2.0'], 3000) },
  { route: '/architecture', instances: one(['Sovereign Infrastructure', 'Five-pillar architecture'], 1500) },
  { route: '/code-changes', instances: one(['Code changes', 'proposed by members'], 600, ['The changes', 'Being decided']) },
  { route: '/compliance', instances: one(['ISO 42001 Alignment', 'This is not a certification claim'], 5000) },
  { route: '/compliance/doc/:slug', instances: COMPLIANCE_DOCS.map((d) => ({ params: { slug: d.slug }, phrases: [d.title, d.sub], minText: 1000 })) },
  { route: '/contact', instances: one(['Talk to the operator', 'Mail lands in front of the person who wrote the code'], 500) },
  { route: '/explore', instances: one(['AGENT DISCOVERY MARKETPLACE', 'Discover, explore, and deploy sovereign AI agents'], 100, ['registries · one network', 'All peers shown']) },
  { route: '/federation-docs', instances: one(['How Federation Works', 'Everything your registry sends, receives, and enforces'], 3000) },
  { route: '/frame-commander', instances: one(['Frame Commander', 'A frame is a digital nation'], 1500) },
  { route: '/getting-started', instances: one(['Getting Started', 'Three levels of participation'], 3000) },
  { route: '/governance-docs', instances: one(['Governance', 'Federation'], 3000) },
  { route: '/legal/:page', legal: true, instances: Object.entries(LEGAL_SUITE_V2).map(([page, doc]) => ({
    params: { page }, phrases: [doc.title, doc.sections?.[0]?.title || doc.title], minText: 800 })) },
  { route: '/logo', instances: one(['Brand Reference', 'Lockups'], 1000) },
  { route: '/migrate', instances: one(['Migrate a system', 'Replace a legacy system'], 600) },
  { route: '/operator', instances: one(['Run a registry', 'Three ways in'], 3000) },
  { route: '/pricing', instances: one(['The price is zero', 'Every tier of TheProtocol is free'], 1000) },
  { route: '/proxy', instances: one(['TheProtocol Proxy', 'It runs beside a system you keep'], 5000) },
  { route: '/roadmap', instances: one(['Roadmap', 'The reactor ships with its control rods'], 3000) },
  { route: '/services', instances: one(['Developer Showcase', 'real agent services running on TheProtocol'], 1500, ['free calls remaining']) },
  { route: '/trust-reputation', instances: one(['Trust & Reputation', 'six-stage graph consensus'], 3000) },
  { route: '/units-and-fees', instances: one(['How units work', 'No blockchain'], 3000) },
  { route: '/whitepaper/:paper?', instances: [
    { params: {}, phrases: ['Cite as', 'TheProtocol'], minText: 3000 },
    { params: { paper: 'quantum' }, phrases: ['Accountable quantum compute', 'Cite as'], minText: 3000 }] },
]

export const PAGES: StaticPage[] = TABLE.map((p) => ({ ...p, paths: p.instances.map((i) => plainPath(p.route, i.params)) }))

/** Every other public route, with the reason it has no static page. */
export const SKIPPED: Record<string, string> = {
  '/agora/listings': 'live data only: every listed organization, read from the books when the page opens',
  '/announcements': "live data only: the registry's announcements, read when the page opens",
  '/become-a-backer': 'a payment door, closed on this registry; nothing to read without it',
  '/become-a-backer/success': "a payment's return page: it confirms one payment",
  '/blog/:slug?': "the blog has its own static generator (scratchpad/gen_blog_static.mjs makes /blog/)",
  '/blueprints': "the blueprints have their own static generator (scratchpad/gen_blueprint_static.mjs makes /blueprints/)",
  '/blueprints/:id': "the blueprints have their own static generator (scratchpad/gen_blueprint_static.mjs makes /blueprints/)",
  '/cards/compare': 'a tool: it compares two agent cards the reader picks',
  '/code-changes/:id': "one change's live record: its state, reviews and ballot change as it goes",
  '/code-changes/new': 'a form: proposing a change needs a signed-in member',
  '/code-changes/track': "the contributor track reads each contributor's unlocks when the page opens",
  '/docs/:chapter?': 'docs.theprotocol.cloud publishes the same documentation as static pages',
  '/email-verification': 'a sign-in step: it answers one verification link',
  '/explore/agent/:did': "one agent's live card",
  '/firms': 'live data only: the organizations that chose full transparency, read when the page opens',
  '/forge': 'a door into the signed-in Forge: two links and a sentence',
  '/forgot-password': 'a sign-in form: it asks for an address and sends a reset link',
  '/founders-wall': 'live data only: the backers, read from the ledger when the page opens',
  '/games-off': 'a notice that a switch is off on this registry',
  '/guild': "live data only: the Guild's open tasks, read when the page opens",
  '/leaderboard': 'live data only: a ranking computed when the page opens',
  '/login': 'a sign-in form: there is nothing to read without an account',
  '/migrate/:id': "one migration template's live record",
  '/migrate/mine': "a member's own templates, read when the page opens",
  '/migrate/new': 'a builder: a form the reader fills in',
  '/migrate/report': 'a tool: it reads a report file the reader drops on it',
  '/migrate/runs': "a member's own migrations, read when the page opens",
  '/monetize': "an example of a member's own service page, not the network's text",
  '/operator-docs/:section?': 'docs.theprotocol.cloud publishes the same operator documentation as static pages',
  '/organizations/invitations/:token/accept': 'an invitation link: it answers one invitation',
  '/proxy/new': 'a builder: a form the reader fills in',
  '/register': 'a sign-in form: it creates an account, the pages it leads to are public already',
  '/reset-password': 'a sign-in form: it answers one reset link',
  '/showcase': 'an animated exchange the reader plays: its text is the animation',
  '/status': 'live data only: the health of the fleet, measured when the page opens',
  '/templates': 'live data only: the template marketplace, read when the page opens',
}
