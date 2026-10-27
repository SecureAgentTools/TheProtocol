import { createRouter, createWebHashHistory } from 'vue-router'
import { replayLocationMissedBeforeReady } from './missedFirstNavigation'
import { loadRegistryConfig } from '@/composables/useRegistryConfig'
import { whenFrameManifest, currentFrameManifest } from '@/composables/useFrameManifest'
import { pocketLockEngaged } from '@/composables/usePocketLock'
import { homeRoute } from '@/services/uiMode'
import type { RouteRecordRaw, Router } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { cannotActReason } from '@/services/agentActable'
import { useUIStore } from '@/stores/ui'
import { useLogger } from '@/composables/useLogger'
import { usePermissions, type AdminAction } from '@/composables/usePermissions'
import { useMainframe } from '@/composables/useMainframe'
import { isStaleChunkError, recoverFromStaleChunk, staleChunkRecovered } from '@/services/staleChunk'

const log = useLogger('router')

// §POCKETBRIDGE5 W-P — DashboardLayout was the ONE eagerly-imported view and
// rode the entry chunk (measured: ~1.9MB entry). Lazy like every other view:
// a phone user in Pocket never pays for the desktop shell, and desktop pays
// for it exactly when it routes there.
const DashboardLayout = () => import('@/layouts/DashboardLayout.vue')

// Define routes
const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'landing',
    component: () => import('@/views/LandingPage.vue'),
    meta: { requiresAuth: false }
  },
  // Enterprise landing — DELETED 2026-08-16 on the Commander's order ("please
  // delete the enterprise page we only use the landing page"). It was already
  // unmounted (§FEDEVENTS-4, 2026-08-03) but the unfinished page kept surfacing
  // as if it were ours; the files are now gone from the tree
  // (EnterpriseLanding.vue, EnterpriseOGCardView.vue, landing/EnterpriseOGCard.vue).
  // The ONE landing page is LandingPage.vue at '/', which the apex root now
  // redirects to. Recoverable from git history if it is ever wanted back.
  // §DISCPUBLIC (2026-09-06, his word) — Agent Discovery WITHOUT a session, for the showcase a new frame
  // shows when it goes to production. The same view: every rail it reads is public already, and it holds no
  // session state; a visitor simply cannot act. The agent card opens in the same modal.
  {
    path: '/explore',
    name: 'public-explore',
    component: () => import('@/views/PublicExplore.vue'),
    meta: { ownsMain: true, requiresAuth: false, title: 'Explore agents' }
  },
  {
    path: '/explore/agent/:did',
    name: 'public-explore-agent',
    component: () => import('@/views/PublicExplore.vue'),
    meta: { ownsMain: true, requiresAuth: false, title: 'Agent' },
    props: true
  },
  // Logo / brand exploration (public, isolated — no shared layout)
  {
    path: '/logo',
    name: 'logo',
    component: () => import('@/views/LogoExample.vue'),
    meta: { requiresAuth: false }
  },
  // Legal pages (public, no layout)
  {
    path: '/legal/:page',
    name: 'legal',
    component: () => import('@/views/LegalPage.vue'),
    meta: { ownsMain: true, requiresAuth: false },
    props: true
  },
  // Oracle documentation (public, no layout)
  {
    path: '/docs/:chapter?',
    name: 'docs',
    component: () => import('@/views/OracleView.vue'),
    meta: { requiresAuth: false },
    props: true
  },
  // Protocol Theatre — A2A showcase (public, no layout)
  {
    path: '/showcase',
    name: 'showcase',
    component: () => import('@/views/ProtocolTheatre.vue'),
    meta: { ownsMain: true, requiresAuth: false }
  },
  // Services Showcase — public agent services (no auth required)
  {
    path: '/services',
    name: 'services',
    component: () => import('@/views/ServicesShowcase.vue'),
    meta: { requiresAuth: false }
  },
  // Industry Blueprints — priority-ordered worked designs per industry, with
  // animated flow looms, attack replays and the safety catalogue. Public.
  // Strategy: PRODUCTION_DOCS/ROADMAP/Industry_Blueprints_Showcase_Strategy.md
  {
    path: '/blueprints',
    name: 'blueprints',
    component: () => import('@/views/BlueprintsView.vue'),
    meta: { requiresAuth: false, title: 'Industry Blueprints' }
  },
  // §18 Atlas split: each industry gets its own chamber. The Atlas above stays
  // the overview; /blueprints?bp=<id> deep links redirect into the chamber.
  {
    path: '/blueprints/:id',
    name: 'blueprint-detail',
    component: () => import('@/views/BlueprintDetailView.vue'),
    meta: { requiresAuth: false, title: 'Industry Blueprint' }
  },
  // Reputation Leaderboard moved 2026-05-08 from top-level (no chrome) to
  // a child of DashboardLayout via `allowAnonymous: true` — gives anonymous
  // visitors the regular sidebar + header without forcing login. See route
  // entry under `/` parent below.
  // Monetization demo — shows what a third-party could build (no auth required)
  {
    path: '/monetize',
    name: 'monetize',
    component: () => import('@/views/MonetizeShowcase.vue'),
    meta: { requiresAuth: false }
  },
  // §pass51 — Public template marketplace landing. No auth.
  // Visitors browse + click "Try this agent" → login → land in /bundles fork flow.
  {
    path: '/templates',
    name: 'public-templates',
    component: () => import('@/views/PublicTemplatesView.vue'),
    meta: { requiresAuth: false, allowAnonymous: true, title: 'Agent Templates' }
  },
  // Network Architecture — public infrastructure showcase (no auth required)
  {
    path: '/architecture',
    name: 'architecture',
    component: () => import('@/views/NetworkArchitecture.vue'),
    meta: { requiresAuth: false }
  },
  // Operator Documentation — 11-chapter technical reference for registry operators
  {
    path: '/operator-docs/:section?',
    name: 'operator-docs',
    component: () => import('@/views/OperatorDocsView.vue'),
    meta: { requiresAuth: false },
    props: true
  },
  // /operator-portal MOVED to DashboardLayout children (2026-05-12) so it
  // renders inside the sidebar+header shell. Owner-facing console — no
  // anonymous access; auth-required keeps the route locked. The previous
  // top-level placement caused the "sidebar disappears when clicking
  // /operator-portal" bug — the page bypassed DashboardLayout entirely.
  // See /operator-portal entry under the `/` parent below.
  // Sovereign frame request — legacy aliases redirect to /frame-commander.
  // /operator/request-frame and /operator?tab=frames-form both land on the
  // dedicated standalone view.
  {
    path: '/operator/request-frame',
    name: 'operator-request-frame',
    redirect: { path: '/frame-commander' },
    meta: { requiresAuth: false, title: 'Request a Frame' }
  },
  {
    path: '/federation-docs',
    name: 'federation-docs',
    component: () => import('@/views/FederationDocs.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/getting-started',
    name: 'getting-started',
    component: () => import('@/views/GettingStartedDocs.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/pricing',
    name: 'pricing',
    component: () => import('@/views/PricingPage.vue'),
    meta: { requiresAuth: false, title: 'Pricing' }
  },
  {
    path: '/contact',
    name: 'contact',
    component: () => import('@/views/ContactPage.vue'),
    meta: { requiresAuth: false, title: 'Contact' }
  },
  {
    path: '/blog/:slug?',
    name: 'blog',
    component: () => import('@/views/BlogView.vue'),
    // §HELLOFRAME ("Ship without it"): a frame without the journal's media offers no journal; a typed /blog goes home
    meta: { requiresAuth: false, title: 'Journal', requiresRegistryFlag: 'journal_enabled', registryFlagRedirect: '/' },
    props: true,
  },
  {
    // /whitepaper is the platform paper; /whitepaper/quantum the accountable-compute paper (WhitepaperView PAPERS).
    path: '/whitepaper/:paper?',
    name: 'whitepaper',
    component: () => import('@/views/WhitepaperView.vue'),
    meta: { requiresAuth: false, title: 'Whitepaper' },
  },
  {
    // The roadmap: where the network is going and the controls that come first. Public; linked from the landing header.
    path: '/roadmap',
    name: 'roadmap',
    component: () => import('@/views/RoadmapView.vue'),
    meta: { requiresAuth: false, title: 'Roadmap' },
  },
  {
    // §STATUSPAGE (2026-09-02) — the public status page; the landing page's status line links here.
    path: '/status',
    name: 'status',
    component: () => import('@/views/StatusPage.vue'),
    meta: { ownsMain: true, requiresAuth: false, title: 'Status' },
  },
  {
    path: '/a2a-protocol',
    name: 'a2a-protocol',
    component: () => import('@/views/A2AProtocolDocs.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/units-and-fees',
    name: 'token-economy',
    component: () => import('@/views/TokenEconomyDocs.vue'),
    // the page reads "Units & Fees", and so do its tab title and, since his word 2026-10-25, its address; the route NAME stays
    meta: { requiresAuth: false, title: 'Units & Fees' }
  },
  // the old address, in links already sent, redirects with its query and hash
  { path: '/token-economy', redirect: (to: any) => ({ path: '/units-and-fees', query: to.query, hash: to.hash }) },
  {
    path: '/governance-docs',
    name: 'governance-docs',
    component: () => import('@/views/GovernanceDocs.vue'),
    meta: { ownsMain: true, requiresAuth: false }
  },
  {
    path: '/trust-reputation',
    name: 'trust-reputation',
    component: () => import('@/views/TrustReputationDocs.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/compliance',
    name: 'compliance',
    component: () => import('@/views/ComplianceDocs.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/compliance/doc/:slug',
    name: 'compliance-doc',
    component: () => import('@/views/ComplianceDoc.vue'),
    meta: { requiresAuth: false }
  },
  // Public routes (no layout)
  {
    // §ORGJOIN (2026-08-28) — the destination of the ACCEPT INVITATION button in
    // org_invitation.html.j2. This path is NOT ours to choose: it is already in
    // every invitation email ever sent, built by send_invitation_email as
    // `{BASE_URL}/ui/#/organizations/invitations/{token}/accept`. It had no route,
    // so every invitee in every signed-in state got "404 PAGE NOT FOUND".
    // requiresAuth is FALSE on purpose — an invitee usually arrives with no
    // session, and being bounced to a login page with no explanation is how you
    // lose someone who was invited by a colleague.
    path: '/organizations/invitations/:token/accept',
    name: 'org-invitation-accept',
    component: () => import('@/views/OrgInvitationAccept.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('@/views/RegisterRefined.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/forgot-password',
    name: 'forgot-password',
    component: () => import('@/views/ForgotPasswordView.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/reset-password',
    name: 'reset-password',
    component: () => import('@/views/ResetPasswordView.vue'),
    meta: { requiresAuth: false }
  },
  // POCKET mode (2026-07-07) — the consumer shell: bottom-tab phone-style UI.
  // Own layout (no sidebar); the full Mission Control stays intact as "Advanced mode".
  {
    path: '/pocket',
    component: () => import('@/views/pocket/PocketShell.vue'),
    meta: { ownsMain: true, requiresAuth: true },
    children: [
      { path: '', redirect: '/pocket/home' },
      { path: 'home', name: 'pocket-home', component: () => import('@/views/pocket/PocketHome.vue'), meta: { requiresAuth: true, title: 'Pocket · Home' } },
      { path: 'trade', name: 'pocket-trade', component: () => import('@/views/pocket/PocketTrade.vue'), meta: { requiresAuth: true, title: 'Pocket · Trade' } },
      // payment-request landing (NFC tag read by the OS, QR scan, shared link) — Home opens Send prefilled
      { path: 'pay', name: 'pocket-pay', component: () => import('@/views/pocket/PocketHome.vue'), meta: { requiresAuth: true, title: 'Pocket · Pay' } },
      { path: 'agents', name: 'pocket-agents', component: () => import('@/views/pocket/PocketAgents.vue'), meta: { requiresAuth: true, title: 'Pocket · Agents' } },
      { path: 'payments', name: 'pocket-earn', component: () => import('@/views/pocket/PocketEarn.vue'), meta: { requiresAuth: true, title: 'Pocket · Payments' } },
      // the address follows the tab's name (his word 2026-10-25); /pocket/earn, in notifications and links already sent, redirects
      { path: 'earn', redirect: (to: any) => ({ name: 'pocket-earn', query: to.query, hash: to.hash }) },
      { path: 'approvals', name: 'pocket-approvals-tab', component: () => import('@/views/PocketApprovals.vue'), meta: { requiresAuth: true, title: 'Pocket · Approvals' } },
      { path: 'activity', name: 'pocket-activity', component: () => import('@/views/pocket/PocketActivity.vue'), meta: { requiresAuth: true, title: 'Pocket · Activity' } },
      { path: 'notifications', name: 'pocket-notification-log', component: () => import('@/views/pocket/PocketNotificationLog.vue'), meta: { requiresAuth: true, title: 'Pocket · Notifications' } },
      // PUBLIC BY NECESSITY. The device approving a sign-in is often the device trying to sign in,
      // which has no session yet — requiring auth here bounced a tapped notification straight to
      // the login page, the exact deadlock the session-free approve endpoint exists to break.
      // Safe: the screen only reads a challenge hash, and approving requires the enrolled
      // authenticator plus a verified human.
      { path: 'approve-login', name: 'pocket-approve-login', component: () => import('@/views/pocket/PocketApproveLogin.vue'), meta: { requiresAuth: false, title: 'Pocket · Approve sign-in' } },
      { path: 'more', name: 'pocket-more', component: () => import('@/views/pocket/PocketMore.vue'), meta: { requiresAuth: true, title: 'Pocket · More' } },
      // §ORGPOCKET (2026-08-28) — organizations had 39 backend routes, a ten-tab
      // desktop dashboard and no phone surface at all. The org id rides the QUERY
      // (?org=<id>) rather than a path segment so the phone back gesture returns
      // to the list instead of leaving Pocket.
      { path: 'orgs', name: 'pocket-orgs', component: () => import('@/views/pocket/PocketOrgs.vue'), meta: { requiresAuth: true, title: 'Pocket · Organizations' } },
      // §POCKETBRIDGE3 — the assistant panel (grammar/bridge/BYO brains) + Connect-Claude onboarding
      // §OURSTATE-1 (2026-08-24) — the chat-native layer. The thread route IS
      // the deep link push notifications target (/ui#/pocket/ourchat/{id}).
      // §ROOMVIEW DESKTOP — NESTED so a wide screen can show the list and the
      // thread at once, while the PATHS and NAMES stay exactly as they were:
      // /pocket/ourchat and /pocket/ourchat/:id still resolve, so every push
      // notification deep link, handle QR and battery `goto` still lands. The
      // shell renders the list itself; the child slot is the thread.
      {
        path: 'ourchat',
        component: () => import('@/views/pocket/OurChatShell.vue'),
        meta: { requiresAuth: true, title: 'Pocket · OurChat' },
        children: [
          // The list lives in the shell, so this child renders nothing: on a
          // phone the shell IS the list, and on desktop the shell shows the
          // "pick a conversation" pane beside it.
          { path: '', name: 'pocket-ourchat', component: { render: () => null },
            meta: { requiresAuth: true, title: 'Pocket · OurChat' } },
          { path: ':id', name: 'pocket-ourchat-thread', component: () => import('@/views/pocket/PocketOurStateThread.vue'), meta: { requiresAuth: true, title: 'Pocket · OurChat' } },
        ],
      },
      // §OURCHAT rename (2026-08-25) — the OLD path is a PERMANENT alias, not a
      // migration window. Deep links to /pocket/ourstate/{id} are already in the
      // wild: every support and chat push notification sent since §OURSTATE-1,
      // every handle QR (`?q=@handle`), and the `?profile=` / `?work=` / `?sheet=`
      // share targets. Those live on devices and in notification trays we do not
      // control, so this alias never gets to expire.
      // ⚠ The redirect is a FUNCTION because a bare `redirect: '/pocket/ourchat'`
      // drops both the params and the query — i.e. it would answer a tapped
      // notification by opening the thread LIST, which reads as "your message is
      // gone". Params, query and hash all travel.
      { path: 'ourstate', redirect: (to: any) => ({ name: 'pocket-ourchat', query: to.query, hash: to.hash }) },
      { path: 'ourstate/:id', redirect: (to: any) => ({ name: 'pocket-ourchat-thread', params: { id: to.params.id }, query: to.query, hash: to.hash }) },
      { path: 'assistant', name: 'pocket-assistant', component: () => import('@/views/pocket/PocketAssistant.vue'), meta: { requiresAuth: true, title: 'Pocket · Assistant' } },
      { path: 'claude', name: 'pocket-claude', component: () => import('@/views/pocket/PocketConnectClaude.vue'), meta: { requiresAuth: true, title: 'Pocket · Use Claude' } },
    ]
  },
  // Authenticated routes with DashboardLayout
  {
    path: '/',
    component: DashboardLayout,
    // §LANDINGTRUTH (28): the layout renders its own <main id="main-content"> (signed-in and visitor branches)
    meta: { ownsMain: true },
    children: [
      // Public Reputation Leaderboard (originally Build #11, relocated 2026-05-08
      // from top-level to here so it gets DashboardLayout's sidebar + header).
      // `allowAnonymous: true` lets DashboardLayout render the shell even
      // without a logged-in user; `requiresAuth: false` keeps the auth guard
      // from redirecting anonymous visitors to /login.
      {
        path: 'leaderboard',
        name: 'leaderboard',
        component: () => import('@/views/Leaderboard.vue'),
        meta: { requiresAuth: false, allowAnonymous: true, title: 'Leaderboard' }
      },
      // §OCOPTIN (2026-08-28) — PUBLIC transparency showcase: firms that opted
      // in serve their records-only work feed here. Same anonymous pattern as
      // the leaderboard. Marker: pf-firms.
      {
        path: 'firms',
        name: 'public-firms',
        component: () => import('@/views/PublicFirms.vue'),
        meta: { requiresAuth: false, allowAnonymous: true, title: 'Firms in the open' }
      },
      // PB-1 fiat onramp — anonymous flow supported (Stripe Checkout w/ email).
      // Mainframe-only at runtime via backend IS_CENTRAL_REGISTRY guard;
      // federated registries return 403 on the API and the page shows that error.
      // Route renamed 2026-05-09: /buy-avt → /become-a-backer (mission-aligned).
      {
        path: 'become-a-backer',
        name: 'become-a-backer',
        // 2026-05-10 — File renamed BuyAVT.vue → BecomeABacker.vue to match
        // the route + the user-facing framing. The page is about backing the
        // network, not buying AVT (the AVT is the boring delivery mechanism).
        component: () => import('@/views/BecomeABacker.vue'),
        // §BAFIN (2026-10-02; the letter: the euro lane and its public price list are off): the door opens only where
        // this registry's own config says the euro lane is on; anywhere else it lands on /pricing, which says so. The
        // /buy-avt aliases below redirect here and meet the same guard.
        meta: { requiresAuth: false, allowAnonymous: true, title: 'Become a Backer', requiresRegistryFlag: 'fiat_onramp_enabled', registryFlagRedirect: '/pricing' }
      },
      {
        path: 'become-a-backer/success',
        name: 'become-a-backer-success',
        component: () => import('@/views/BackerWelcome.vue'),
        meta: { requiresAuth: false, allowAnonymous: true, title: 'Backer Welcome', requiresRegistryFlag: 'fiat_onramp_enabled', registryFlagRedirect: '/pricing' }
      },
      // Legacy aliases — old /buy-avt links keep working (bookmarks, email, Stripe metadata).
      { path: 'buy-avt',         redirect: '/become-a-backer' },
      { path: 'buy-avt/success', redirect: { name: 'become-a-backer-success' } },
      // PB-1 backer flare manager — auth required (cosmetic profile + agent badge management)
      {
        path: 'flare-manager',
        name: 'flare-manager',
        component: () => import('@/views/FlareManager.vue'),
        meta: { requiresAuth: true, title: 'My Flare', viewAmbientTone: 'sovereign'  }
      },
      // §FLARESHOP (2026-08-16) — the BUY side, paid in the frame's own currency.
      // /flare-manager is the WEAR side; the two link to each other and share the
      // FlareEncirclement renderer. Auth required to purchase, but the catalog
      // itself renders for anyone who reaches the view (and the whole gallery
      // renders even where the lane is disabled — see the view's header comment).
      {
        path: 'flare-shop',
        name: 'flare-shop',
        component: () => import('@/views/FlareShop.vue'),
        meta: { requiresAuth: true, title: 'Flare Shop', viewAmbientTone: 'sovereign' }
      },
      {
        path: 'founders-wall',
        name: 'founders-wall',
        component: () => import('@/views/FoundersWall.vue'),
        // §BAFIN: the wall is a euro offer (tiers, bonuses, scarcity); it exists only where the euro lane is on
        meta: { requiresAuth: false, allowAnonymous: true, title: 'Founders Wall', viewAmbientTone: 'sovereign', requiresRegistryFlag: 'fiat_onramp_enabled', registryFlagRedirect: '/' }
      },
      // 2026-05-11 PB-1 §67 — Operator unified pitch (4 tabs: Overview / Cloud /
      // Self-Hosted / Frames). Anonymous-friendly via DashboardLayout shell so
      // visitors get the sidebar with all the context. Same wrapping pattern as
      // /founders-wall + /become-a-backer.
      {
        path: 'operator',
        name: 'operator',
        component: () => import('@/views/OperatorPage.vue'),
        meta: { requiresAuth: false, allowAnonymous: true, title: 'Operator' }
      },
      // Frame Commander — sovereign frame request (standalone, deeper than the
      // Frames tab on /operator). Public, allowAnonymous so the form lives
      // inside the sidebar shell. Auto-create-account checkbox optional.
      {
        path: 'frame-commander',
        name: 'frame-commander',
        component: () => import('@/views/FrameCommander.vue'),
        meta: { requiresAuth: false, allowAnonymous: true, title: 'Frame Commander', viewAmbientTone: 'sovereign'  }
      },
      // §HELLOFRAME (2026-09-19): the applicant's own frame page and the frame kit download. Behind FRAME_KIT_ENABLED
      // (off by default): the guard below sends a typed URL to the dashboard when the flag is off, and the registry
      // answers 404 there too.
      {
        path: 'frame-kit',
        name: 'frame-kit',
        component: () => import('@/views/FrameKit.vue'),
        meta: { requiresAuth: true, requiresRegistryFlag: 'frame_kit_enabled', title: 'Your frame', viewAmbientTone: 'sovereign' }
      },
      // Operator Portal — owner-facing console (eligibility · my ops · provision · bundle).
      // 2026-05-12: relocated from top-level to here so the sidebar+header shell renders.
      // requiresAuth — no anon access (the portal shows the dev's own state).
      {
        path: 'operator-portal',
        name: 'operator-portal',
        component: () => import('@/views/OperatorPortal.vue'),
        meta: { requiresAuth: true, title: 'Operator Portal', viewAmbientTone: 'sovereign'  }
      },
      // Admin-only — fiat operations console (overview · pricing · simulator · purchase explorer · manual ops)
      {
        path: 'admin/fiat-ops',
        name: 'admin-fiat-ops',
        component: () => import('@/views/AdminFiatOps.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'treasury', title: 'Fiat Operations', viewAmbientTone: 'admin'  }
      },
      // Legacy alias for the old route — keep navigation working for bookmarks
      {
        path: 'admin/fiat-pricing',
        redirect: '/admin/fiat-ops',
      },
      {
        // §DASHRESTORE (2026-09-02, his call) — /mission-control is the
        // NEURAL COMMAND DASHBOARD again: the pre-§BRIDGE view, recovered from
        // the 2026-08-18 blueprint snapshot (the last of five days it sat
        // unchanged at 137,078 bytes before §BRIDGE P1 rewrote it overnight).
        // It is the post-login landing because it is dashboard-shaped and
        // mounts NO WebGL — verified: zero Cesium/three/canvas references, so
        // it cannot repeat the 22s globe fetch that made the old landing paint
        // at ~25s. The 3D bridge is not retired; it moved to /bridge with its
        // own sidebar entry, on his word ("bridge gets bridge menu item").
        path: 'mission-control',
        name: 'mission-control',
        component: () => import('@/views/MissionControl.vue'),
        meta: { requiresAuth: true }
      },
      {
        // §DASHRESTORE — today's §BRIDGE view (P1-R15), unchanged, at its own
        // route. ⚠ missionControl.tour.ts + missionControlLite.tour.ts anchor
        // THIS view (bridge-stage, bridge-ledger, bridge-pulse, …) and their
        // `route:` fields were repointed here in the same change. Leaving them
        // on /mission-control would not have errored — §OPGUIDE-7: a step whose
        // data-tour is absent degrades to a centred card and quietly lies.
        path: 'bridge',
        name: 'bridge',
        component: () => import('@/views/Bridge.vue'),
        meta: { requiresAuth: true }
      },
      {
        path: 'discovery',
        name: 'discovery',
        component: () => import('@/views/GalacticMap.vue'),
        meta: { requiresAuth: true, requiresAgent: true }
      },
      {
        path: 'senate',
        name: 'senate',
        component: () => import('@/views/SenateFloor.vue'),
        meta: { requiresAuth: true, requiresAgent: true, viewAmbientTone: 'sovereign'  }
      },
      {
        // §MEMBERSHIP phase C (design § 12 S5): every registry with its members and its commons; no price, by design.
        // Open only where this registry runs governance by membership or a commons; anywhere else (production, until
        // his word) a typed URL lands where the console starts, like any page switched off on this registry.
        path: 'registries',
        name: 'registries',
        component: () => import('@/views/RegistryBoard.vue'),
        meta: { requiresAuth: true, requiresRegistryAny: [['governance_weight_mode', 'member'], ['commons_enabled', true]] }
      },
      {
        path: 'galactic-map',
        name: 'galactic-map',
        component: () => import('@/views/GalacticMap.vue'),
        meta: {
          requiresAuth: true,
          title: 'Galactic Map'
        }
      },
      {
        path: 'agentworld',
        name: 'agentworld',
        component: () => import('@/views/AgentWorldCesium.vue'),
        meta: {
          requiresAuth: true,
          title: 'AgentWorld'
        }
      },
      {
        path: 'universe',
        name: 'universe',
        component: () => import('@/views/UniverseView.vue'),
        meta: {
          requiresAuth: true,
          title: 'Universe View'
        }
      },
      {
        path: 'contracts',
        name: 'contracts',
        component: () => import('@/views/Contracts.vue'),
        meta: {
          requiresAuth: true,
          // 2026-07-25: requiresAgent DROPPED (Commander bug: sidebar search → Contracts bounced
          // to onboarding via the credential-less branch of the agent guard). The view is
          // dual-auth (X34): browsing/analytics/templates work on a developer JWT; every
          // mutation mints an agent JWT per-action itself.
          title: 'Contract Management',
          viewAmbientTone: 'default'
        }
      },
      {
        // §COCKPIT P1 (2026-08-31) — THE DESK. Deliberately NOT overloaded onto
        // /cockpit: that path is the Cockpit CARD (mandates + evidence chain) and
        // has been in the sidebar since July. The desk is a different surface on
        // the same rails. Gated by `meta.requiresRegistryFlag`, resolved in the
        // global guard against the SAME public-config read the sidebar uses.
        path: 'desk',
        name: 'cockpit-desk',
        component: () => import('@/views/CockpitDesk.vue'),
        meta: {
          requiresAuth: true,
          requiresRegistryFlag: 'cockpit_desk_enabled',
          title: 'Cockpit Desk',
          viewAmbientTone: 'default'
        }
      },
      {
        path: 'cockpit',
        name: 'cockpit',
        component: () => import('@/views/CockpitCard.vue'),
        meta: {
          requiresAuth: true,
          // COCKPIT CARD (2026-07-25): dev-JWT surface by design — the LIABLE HUMAN manages
          // mandates/confirms here (agents never do). No requiresAgent (Contracts X33 lesson).
          title: 'Cockpit Card',
          viewAmbientTone: 'default'
        }
      },
      {
        path: 'disputes',
        name: 'disputes',
        component: () => import('@/views/Disputes.vue'),
        meta: {
          requiresAuth: true,
          requiresAgent: true,
          title: 'Dispute Resolution',
          viewAmbientTone: 'default'
        }
      },
      {
        path: 'settlements',
        name: 'settlements',
        component: () => import('@/views/Settlements.vue'),
        meta: {
          requiresAuth: true,
          requiresRole: 'admin',
          requiresAdminFlag: 'enforcement',
          title: 'Cross-Registry Settlements'
        }
      },
      {
        path: 'admin/enforcement',
        name: 'admin-enforcement',
        component: () => import('@/views/AdminEnforcement.vue'),
        meta: {
          requiresAuth: true,
          requiresRole: 'admin',
          requiresAdminFlag: 'enforcement',
          title: 'Economic Enforcement',
          viewAmbientTone: 'security'
        }
      },
      {
        path: 'admin/jurisdiction',
        name: 'admin-jurisdiction',
        component: () => import('@/views/AdminJurisdiction.vue'),
        meta: {
          requiresAuth: true,
          requiresRole: 'admin',
          requiresAdminFlag: 'platform',
          title: 'Jurisdiction and Regulatory Authorizations',
          viewAmbientTone: 'security'
        }
      },
      {
        path: 'command-center',
        name: 'command-center',
        component: () => import('@/views/CommandCenter.vue'),
        meta: {
          requiresAuth: true,
          requiresRole: 'admin',
          requiresAdminFlag: 'platform',
          title: 'Command Center'
        }
      },
      {
        path: 'discover',
        name: 'discover',
        component: () => import('@/views/Discovery.vue'),
        meta: {
          requiresAuth: true,
          title: 'Agent Discovery'
        }
      },
      {
        path: 'my-agents',
        name: 'my-agents',
        component: () => import('@/views/MyAgents.vue'),
        meta: { requiresAuth: true, viewAmbientTone: 'default' }
      },
      {
        // PHONE FABRIC console (2026-07-07) — admin oversight for capability-gated agent computer-use.
        path: 'phone-fabric',
        name: 'phone-fabric',
        component: () => import('@/views/PhoneFabricConsole.vue'),
        // §FESUITE: an admin console (kill sessions, global halt) whose every rail is admin-only; a member got a 403
        // from it every 8 s for as long as the page stayed open.
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'platform', title: 'Phone Fabric' }
      },
      {
        // THE GUILD (2026-07-07) — agent work exchange board + admin oversight.
        path: 'guild',
        name: 'guild',
        component: () => import('@/views/GuildBoard.vue'),
        meta: { requiresAuth: false, allowAnonymous: true, title: 'The Guild' }
      },
      {
        path: 'forge',
        name: 'forge',
        component: () => import('@/views/GodelForge.vue'),
        meta: { requiresAuth: false, allowAnonymous: true, title: 'GÖDEL FORGE' }
      },
      {
        // POCKET FRAME (2026-07-07) — pair phone + push devices
        path: 'pocket-frame',
        name: 'pocket-frame',
        component: () => import('@/views/PocketFrame.vue'),
        meta: { requiresAuth: true, title: 'POCKET FRAME' }
      },
      {
        // POCKET FRAME — IRONKEY approvals + panic control
        path: 'pocket-approvals',
        name: 'pocket-approvals',
        component: () => import('@/views/PocketApprovals.vue'),
        meta: { requiresAuth: true, title: 'Approvals & Control' }
      },
      {
        // Quick onboarding (2026-10-09, his word): /onboarding issues an agent identity from a name (a DID, a standard
        // A2A card, the credentials, shown once), lists the developer's agents with their balances hidden until asked,
        // and resets an agent's credentials. It rendered AgentForge until now, the same page as /agent-builder and
        // /agent-forge below (two sidebar rows, one page); the builder keeps those two routes, unchanged.
        path: 'onboarding',
        name: 'onboarding',
        component: () => import('@/views/QuickOnboarding.vue'),
        meta: {
          requiresAuth: true,
          title: 'Quick onboarding',
          viewAmbientTone: 'cyan'
        }
      },
      {
        path: 'federation',
        name: 'federation',
        component: () => import('@/views/Federation.vue'),
        meta: { requiresAuth: true, viewAmbientTone: 'sovereign'  }
      },
      {
        // §pass62 (2026-05-21) — Federation peer browse view (parallel to Agent Discovery).
        // §pass62.1 (2026-05-21) — Renamed page title "Federation Discovery" → "Federation Peers".
        // Route path kept (/federation-discover) for backward-compat with existing links.
        path: 'federation-discover',
        name: 'federation-discover',
        component: () => import('@/views/FederationDiscovery.vue'),
        meta: { requiresAuth: true, viewAmbientTone: 'sovereign', title: 'Federation Peers' }
      },
      {
        // Agent Builder — back-compat alias for AgentForge.
        path: 'agent-builder',
        name: 'agent-builder',
        component: () => import('@/views/AgentForge.vue'),
        meta: { requiresAuth: true, title: 'Agent Forge' }
      },
      {
        // Canonical name for the consolidated wizard.
        path: 'agent-forge',
        name: 'agent-forge',
        component: () => import('@/views/AgentForge.vue'),
        meta: { requiresAuth: true, title: 'Agent Forge' }
      },
      {
        // §EXCISION-10 — forced password change. Sits inside the authenticated tree so
        // the session is available, but the guard below refuses every OTHER destination
        // while the flag is set, so it behaves as a hard stop.
        path: 'force-password-change',
        name: 'force-password-change',
        component: () => import('@/views/ForcePasswordChange.vue'),
        meta: { requiresAuth: true }
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/Settings.vue'),
        meta: { requiresAuth: true }
      },
      {
        path: 'api-keys',
        name: 'api-keys',
        component: () => import('@/views/ApiKeys.vue'),
        meta: { requiresAuth: true }
      },

      {
        path: 'webhooks',
        name: 'webhooks',
        component: () => import('@/views/WebhookManager.vue'),
        meta: { 
          requiresAuth: true,
          title: 'Webhook Management'
        }
      },
      {
        path: 'organization',
        name: 'organization',
        component: () => import('@/views/OrganizationDashboard.vue'),
        meta: {
          requiresAuth: true,
          title: 'Organizations & Teams',
          viewAmbientTone: 'default'
        }
      },
      {
        // §pass51 (2026-05-20) — /export-import replaced by /bundles. Old path
        // 301-redirects so any bookmark / link survives.
        path: 'export-import',
        redirect: { name: 'bundles' }
      },
      {
        path: 'bundles',
        name: 'bundles',
        component: () => import('@/views/BundlesView.vue'),
        meta: {
          requiresAuth: true,
          title: 'Agent Bundles',
          viewAmbientTone: 'default'
        }
      },
      {
        path: 'bundles/:bundleId',
        name: 'bundle-detail',
        component: () => import('@/views/BundlesView.vue'),
        meta: {
          requiresAuth: true,
          title: 'Agent Bundle',
          viewAmbientTone: 'default'
        }
      },
      {
        path: 'health-monitor',
        name: 'health-monitor',
        component: () => import('@/views/HealthMonitorUltimate.vue'),
        meta: {
          requiresAuth: true,
          requiresDeveloper: true,
          requiresRole: 'admin',
          requiresAdminFlag: 'platform',
          title: 'Health Monitor',
          viewAmbientTone: 'admin'
        }
      },
      {
        path: 'operator-management',
        name: 'operator-management',
        component: () => import('@/views/OperatorManagement.vue'),
        // §pass66 — mainframe-only. Cloud-ops can't provision sub-operators.
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'federation', requiresMainframe: true }
      },
      {
        path: 'frame-management',
        name: 'frame-management',
        component: () => import('@/views/FrameManagement.vue'),
        // §pass66 — mainframe-only. Cross-frame bridge config is mainframe-tier.
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'federation', requiresMainframe: true, title: 'Frame Management', viewAmbientTone: 'sovereign'  }
      },
      {
        path: 'admin/ironhand',
        name: 'ironhand-monitor',
        component: () => import('@/views/IronhandMonitor.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'platform', viewAmbientTone: 'security'  }
      },
      {
        // IRONHAND mTLS Identity Theatre — flagship live identity-travel terminal.
        // On EVERY frame + operator (no requiresMainframe).
        path: 'ironhand/theatre',
        name: 'ironhand-theatre',
        component: () => import('@/views/IronhandTheatre.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'platform', title: 'mTLS Identity Theatre', viewAmbientTone: 'security' }
      },
      {
        // Galactic Command Center (GCC) — fleet-wide map cockpit: click a
        // registry/agent node, the Bridge panel retargets and executes admin
        // actions against the selection. On every frame + operator.
        path: 'galactic-command',
        name: 'galactic-command',
        component: () => import('@/views/GalacticCommand.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'platform', title: 'Galactic Command', viewAmbientTone: 'admin' }
      },
      {
        path: 'admin/compliance',
        name: 'consul-compliance-monitor',
        component: () => import('@/views/ComplianceMonitor.vue'),
        // §DRIFTSKIP (2026-09-09): the guard said `federation` while routers/consul_admin.py
        // enforces `admin_platform` on every endpoint this page calls. A federation-only admin
        // therefore passed the guard and then 403'd on the whole screen. Guard on what the
        // BACKEND actually requires, so the nav item is absent rather than a dead end.
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'platform', title: 'CONSUL — Federation Compliance', viewAmbientTone: 'security'  }
      },
      {
        path: 'admin/opa',
        name: 'opa-console',
        component: () => import('@/views/OpaConsole.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'platform', title: 'OPA — Policy Console', viewAmbientTone: 'security' }
      },
      {
        path: 'admin/developers',
        name: 'admin-developers',
        component: () => import('@/views/AdminDevelopers.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'platform', title: 'Developer Management', viewAmbientTone: 'admin'  }
      },
      {
        // Registry Card v0.3 editor (2026-05-21)
        path: 'admin/registry-card',
        name: 'admin-registry-card',
        component: () => import('@/views/RegistryCardEditor.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'platform', title: 'Registry Card v0.3', viewAmbientTone: 'admin' }
      },
      {
        path: 'admin/agents',
        name: 'admin-agents',
        component: () => import('@/views/AdminAgents.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'platform', title: 'Agent Management', viewAmbientTone: 'admin'  }
      },
      {
        path: 'admin/reactors',
        name: 'admin-reactors',
        component: () => import('@/views/AdminReactors.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'platform', title: 'Reactor Framework', viewAmbientTone: 'admin'  }
      },
      {
        path: 'admin/release-channel',
        name: 'admin-release-channel',
        component: () => import('@/views/AdminReleaseChannel.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'platform', title: 'Release channel', viewAmbientTone: 'admin' }
      },
      {
        path: 'admin/evals',
        name: 'admin-evals',
        component: () => import('@/views/AdminEvals.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'platform', title: 'Agent Evals', viewAmbientTone: 'admin' }
      },
      {
        // Phase 5 + 6 (2026-05-26): MCP regression-coverage sweeper
        path: 'admin/mcp-tester',
        name: 'admin-mcp-tester',
        component: () => import('@/views/AdminMcpTester.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'platform', title: 'MCP Tester', viewAmbientTone: 'admin' }
      },
      {
        // §MCPTEST30 (V0555): the console suite's runs (the host's browser lifecycles), recorded by its runner
        path: 'admin/console-suite',
        name: 'admin-console-suite',
        component: () => import('@/views/AdminConsoleSuite.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'platform', title: 'Console Suite', viewAmbientTone: 'admin' }
      },
      {
        // Build #6 (2026-05-07): EventStore Explorer — admin ledger browser
        path: 'admin/events',
        name: 'admin-events',
        component: () => import('@/views/AdminEvents.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'platform', title: 'EventStore Explorer', viewAmbientTone: 'admin'  }
      },
      {
        // 2026-06-19: Ledger Forensics — stuck-funds tracer + AGORA/supply
        // invariants + f037 emission-policy console. Frontend-only over existing
        // admin endpoints; backend forensics router (Inventory/Query/verdict) pending.
        path: 'admin/forensics',
        name: 'admin-forensics',
        component: () => import('@/views/LedgerForensics.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'platform', title: 'Ledger Forensics', viewAmbientTone: 'admin'  }
      },
      {
        // W3 (agentvault2-d6's read, agentvault2-69's page, 2026-10-25; his word "i really need it visualized"): the
        // effective emission-policy configuration, one row per event type; admin_treasury, as the read behind it.
        path: 'admin/emission-policy',
        name: 'admin-emission-policy',
        component: () => import('@/views/AdminEmissionPolicy.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'treasury', title: 'Emission Policy', viewAmbientTone: 'admin' }
      },
      {
        // §pass49 F1 (2026-05-19): Admin CI/CD Fleet view
        path: 'admin/cicd',
        name: 'admin-cicd',
        component: () => import('@/views/AdminCICD.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'platform', title: 'CI/CD Fleet', viewAmbientTone: 'admin'  }
      },
      {
        // §pass49 F4 (2026-05-19): Admin Audit Logs view (security_audit_logs)
        path: 'admin/audit-logs',
        name: 'admin-audit-logs',
        component: () => import('@/views/AdminAuditLogs.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'platform', title: 'Audit Logs', viewAmbientTone: 'admin'  }
      },
      {
        // §pass51 P42 — Bundle marketplace moderation (admin_enforcement)
        path: 'admin/marketplace',
        name: 'admin-marketplace',
        component: () => import('@/views/AdminMarketplace.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'enforcement', title: 'Marketplace Moderation', viewAmbientTone: 'admin' }
      },
      {
        // Build #7 (2026-05-07): Treasury & Fee Audit Dashboard — supply
        // conservation + treasury balance + fee flows + mint provenance.
        path: 'admin/treasury',
        name: 'admin-treasury',
        component: () => import('@/views/AdminTreasury.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'treasury', title: 'Treasury & Fee Audit', viewAmbientTone: 'admin'  }
      },
      {
        // §FX (2026-06-02): Cross-Frame FX Desk — the AVT⇄BVT reserve-mediated
        // swap booth console (live pool/rate/config + swap feed + quote sim).
        // Treasury-gated. Integrity panel pending a cross-frame-audit proxy (B8).
        path: 'admin/fx',
        name: 'admin-fx',
        component: () => import('@/views/AdminFx.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'treasury', title: 'Cross-Frame FX Desk', viewAmbientTone: 'admin'  }
      },
      {
        // §V0064 (2026-06-13): AGORA venue command — listings lifecycle,
        // I-X1..4 conservation panel, compliance registry, global halt.
        // Federation-gated (backend = require_admin_flag('admin_federation')).
        path: 'admin/agora',
        name: 'admin-exchange',
        component: () => import('@/views/AdminExchange.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'federation', title: 'AGORA Administration', viewAmbientTone: 'admin'  }
      },
      // §AGORAWORDS (V0419): the old path stays as a redirect FUNCTION (a bare string
      // redirect drops the query and the hash; notification deep links carry both).
      { path: 'admin/exchange', redirect: (to: any) => ({ name: 'admin-exchange', query: to.query, hash: to.hash }) },
      {
        // Build #8 (2026-05-07): Webhook Watchtower — cluster-wide delivery
        // health, top-failing endpoints, recent deliveries feed.
        path: 'admin/webhooks-cluster',
        name: 'admin-webhooks-cluster',
        component: () => import('@/views/AdminWebhooks.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'platform', title: 'Webhook Watchtower', viewAmbientTone: 'admin'  }
      },
      {
        // Build #9 (2026-05-07): Cross-Frame Bridge Watchtower — async
        // cross-frame transfers + SF-3 sync bridge transactions.
        path: 'admin/bridge',
        name: 'admin-bridge',
        component: () => import('@/views/AdminBridge.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'federation', title: 'Cross-Frame Bridge', viewAmbientTone: 'admin'  }
      },
      {
        // Build #10 (2026-05-07): Email Studio — preview all transactional
        // and reactor email templates with theme variants. Pure-frontend
        // on top of /admin/email/preview/* endpoints.
        path: 'admin/email',
        name: 'admin-email',
        component: () => import('@/views/AdminEmail.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'platform', title: 'Email Studio', viewAmbientTone: 'admin'  }
      },
      {
        // §FRAMEMAIL-5 (2026-08-02): Mail Console — fleet-wide mail posture.
        // Separate from Email Studio on purpose: Studio is about what a message
        // LOOKS like, this is about whether a node can send one at all. Backend
        // 404s where no mail credentials are held, so the view is only useful
        // on the registry that owns the shared sender.
        path: 'admin/mail-fleet',
        name: 'admin-mail-fleet',
        component: () => import('@/views/AdminMailFleet.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'platform', title: 'Mail Console', viewAmbientTone: 'admin'  }
      },
      {
        // §pass40 (2026-05-18): Admin Broadcasts — full-management view for
        // the broadcast/announcement system. Stats, compose, edit, retract,
        // reinstate, read tracking. Gated to admin_support (same as the
        // backend POST /admin/broadcasts endpoint).
        path: 'admin/broadcasts',
        name: 'admin-broadcasts',
        component: () => import('@/views/AdminBroadcasts.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'support', title: 'Broadcasts', viewAmbientTone: 'admin'  }
      },
      {
        // §ADMINDESK (2026-08-29) — the operator's OurChat-style chat desk.
        // Two lanes only (support threads + customer-granted reviews); every
        // transcript open writes an audit row. Gated admin_support, matching
        // the backend routes it consumes.
        path: 'admin/chatdesk',
        name: 'admin-chatdesk',
        component: () => import('@/views/AdminChatDesk.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'support', title: 'Chat Desk', viewAmbientTone: 'admin'  }
      },
      {
        // Build #12 (2026-05-07): Settlements Watchtower — cross-registry
        // dispute compensation slash + mint flows.
        path: 'admin/settlements',
        name: 'admin-settlements',
        component: () => import('@/views/AdminSettlements.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'enforcement', title: 'Settlements', viewAmbientTone: 'admin'  }
      },
      // §pass37 (2026-05-18) — standalone /admin/agent-card-drift route removed;
      // drift surfaces folded into AdminAgents.vue (compound Signals column +
      // Card Sync drawer tab + bulk "More ▾" actions). Backend routes stay live.
      {
        // Build #13 (2026-05-07; REWRITTEN 2026-05-08 polish pass):
        // Federation Peer Operations — merged into Federation.vue as the
        // Operations tab (admin-gated). Standalone route kept as a redirect
        // so old bookmarks still work.
        path: 'admin/peers',
        redirect: '/federation?tab=operations',
      },
      {
        // Build #14 (2026-05-08): ZKP Attestation Analytics — circuit
        // distribution, status breakdown, submission cadence, recent activity.
        path: 'admin/attestation-analytics',
        name: 'admin-attestation-analytics',
        component: () => import('@/views/AdminAttestationAnalytics.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'platform', title: 'Attestation Analytics', viewAmbientTone: 'admin'  }
      },
      {
        path: 'admin/canaries',
        name: 'admin-canaries',
        component: () => import('@/views/AdminCanaries.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'platform', title: 'Canary Transfer System', viewAmbientTone: 'admin'  }
      },
      {
        // ZKP Maturation Phase 6 (2026-04-28): agent-facing attestation view
        // 2026-05-07: added requiresAgent — schedules/submit/revoke require
        // agent JWT, so without an active agent the view 401-cascaded into
        // logout + CrowdSec IP ban. Route guard now prompts agent picker first.
        path: 'attestations',
        name: 'attestations',
        component: () => import('@/views/AgentAttestations.vue'),
        meta: { requiresAuth: true, requiresAgent: true, title: 'ZKP Attestations', viewAmbientTone: 'security'  }
      },
      {
        // ZKP Maturation Phase 6 (2026-04-28): admin-facing attestation audit
        path: 'admin/attestations',
        name: 'admin-attestations',
        component: () => import('@/views/AdminAttestations.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'platform', title: 'ZKP Attestation Audit', viewAmbientTone: 'security'  }
      },
      {
        path: 'eigentrust-command',
        name: 'eigentrust-command',
        component: () => import('@/views/EigenTrustCommand.vue'),
        meta: { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'platform', title: 'EigenTrust Command' }
      },
      {
        path: 'api-tester',
        name: 'api-tester',
        component: () => import('@/views/ApiTesterContainer.vue'),
        meta: {
          requiresAuth: true,
          // §FESUITE: every call this page makes is an admin_platform rail; a member reached a page that crashed on
          // its first 403 (an error boundary). It is the platform admins' tool, as its own rails always said.
          requiresRole: 'admin',
          requiresAdminFlag: 'platform',
          title: 'API Testing Suite',
          viewAmbientTone: 'admin'
        }
      },
      {
        path: 'federation-test',
        name: 'federation-test',
        component: () => import('@/views/FederationTestDashboard.vue'),
        meta: {
          requiresAuth: true,
          requiresDeveloper: true,
          requiresRole: 'admin',
          requiresAdminFlag: 'federation',
          title: 'Federation Test Dashboard'
        }
      },
      {
        path: 'games',
        name: 'games',
        component: () => import('@/views/GamesHub.vue'),
        meta: {
          requiresAuth: true,
          title: 'Game Arena'
        }
      },
      {
        path: 'arena',
        name: 'arena',
        component: () => import('@/views/ArenaView.vue'),
        meta: {
          requiresAuth: true,
          title: 'Robo Wars Arena'
        }
      },
      {
        path: 'tower-defense',
        name: 'tower-defense',
        component: () => import('@/views/TowerDefenseView.vue'),
        meta: {
          requiresAuth: true,
          title: 'Tower Defense'
        }
      },
      {
        path: 'snake-arena',
        name: 'snake-arena',
        component: () => import('@/views/SnakeArenaView.vue'),
        meta: { requiresAuth: true, title: 'Snake Arena' }
      },
      {
        path: 'trading',
        name: 'trading',
        component: () => import('@/views/TradingView.vue'),
        meta: { requiresAuth: true, title: 'Market Mayhem' }
      },
      {
        path: 'protocol-theatre',
        name: 'protocol-theatre',
        component: () => import('@/views/ProtocolTheatre.vue'),
        meta: { requiresAuth: true, title: 'Protocol Theatre' }
      },
      // §pass63 (2026-05-22) — 10 Astraeus routes (landing/dashboard/cockpit/
      // leaderboard/codex/bases/questlines/orgs/spectator/careers) removed
      // alongside the views/astraeus/ directory.
      {
        path: 'agent-tutorial',
        redirect: { name: 'tutorials' }
      },
      {
        path: 'tutorials',
        name: 'tutorials',
        component: () => import('@/views/Tutorials/TutorialHub.vue'),
        meta: {
          requiresAuth: true,
          requiresDeveloper: true,
          title: 'API Tutorials'
        }
      },
      {
        path: 'tutorials/:trackId',
        name: 'tutorial-runner',
        component: () => import('@/views/Tutorials/TutorialRunner.vue'),
        meta: {
          requiresAuth: true,
          requiresDeveloper: true,
          title: 'Tutorial'
        },
        props: true
      },
      {
        path: 'locks',
        name: 'staking',
        component: () => import('@/views/StakingView.vue'),
        meta: {
          requiresAuth: true,
          requiresAgent: true,
          // §BAFIN: unreachable where the registry switched locking off (the sidebar reads the same flag)
          requiresRegistryFlag: 'staking_enabled',
          registryFlagRedirect: '/mission-control',
          title: 'Locks',
          viewAmbientTone: 'default'
        }
      },
      // the lock desk's address (his word 2026-10-25); /staking redirects with its query and hash, the route NAME stays
      { path: 'staking', redirect: (to: any) => ({ name: 'staking', query: to.query, hash: to.hash }) },
      {
        path: 'forex',
        name: 'forex',
        component: () => import('@/views/ForexDesk.vue'),
        meta: {
          requiresAuth: true,
          requiresAgent: true,
          title: 'Forex Desk',
          viewAmbientTone: 'default'
        }
      },
      {
        path: 'agora',
        name: 'exchange',
        component: () => import('@/views/ExchangeDesk.vue'),
        meta: {
          requiresAuth: true,
          requiresAgent: true,
          title: 'AGORA Desk',
          viewAmbientTone: 'cyan'
        }
      },
      // §AGORAWORDS (V0419): /exchange and /stocks stay as redirect FUNCTIONS so every
      // bookmark, tour step and notification link keeps its query (?sym=, ?venue=) and hash.
      { path: 'exchange', redirect: (to: any) => ({ name: 'exchange', query: to.query, hash: to.hash }) },
      {
        // §V0064 P2 (2026-06-13): federation equity screener — every venue's
        // listings, passport buy for foreign books. Browse needs no agent.
        path: 'agora/listings',
        name: 'stocks',
        component: () => import('@/views/StockDiscovery.vue'),
        // 2026-06-17 — PUBLIC network-wide equity discovery. Anonymous renders
        // the DashboardLayout shell for this route (same pattern as
        // become-a-backer). Browse needs no auth; passport-buy self-disables
        // for guests (StockDiscovery handles the guest path).
        meta: {
          requiresAuth: false,
          allowAnonymous: true,
          title: 'AGORA Listings',
          viewAmbientTone: 'cyan'
        }
      },
      { path: 'stocks', redirect: (to: any) => ({ name: 'stocks', query: to.query, hash: to.hash }) },
      {
        path: 'email-verification',
        name: 'email-verification',
        component: () => import('@/views/EmailVerification.vue'),
        meta: { 
          requiresAuth: false,
          title: 'Email Verification'
        }
      },
      {
        path: 'agent/:agentId',
        name: 'agent-details',
        component: () => import('@/views/AgentDetails.vue'),
        meta: { 
          requiresAuth: true,
          title: 'Agent Details'
        }
      },
      {
        path: 'agent-profile/:did',
        name: 'agent-profile',
        component: () => import('@/views/AgentProfile.vue'),
        meta: { requiresAuth: true }
      },
      {
        path: 'agent/:did/ci-cd',
        name: 'agent-cicd',
        component: () => import('@/views/AgentCICD.vue'),
        meta: {
          requiresAuth: true,
          title: 'CI/CD Management',
          viewAmbientTone: 'default'
        }
      },
      {
        path: 'ci-cd',
        name: 'ci-cd',
        component: () => import('@/views/CICDList.vue'),
        meta: {
          requiresAuth: true,
          title: 'CI/CD Pipelines',
          viewAmbientTone: 'default'
        }
      },
      {
        path: 'community',
        name: 'community',
        component: () => import('@/views/CommunityView.vue'),
        meta: {
          requiresAuth: true,
          title: 'Community'
        }
      },
      {
        path: 'ourchat',
        component: () => import('@/views/pocket/OurChatShell.vue'),
        meta: { requiresAuth: true, title: 'OurChat' },
        // §CHATDESK C2 — the DESKTOP mount of OurChat: same shell, same children
        // shape as /pocket/ourchat. Deep links, push notifications and the
        // permanent /pocket/ourstate alias keep targeting the Pocket paths —
        // that contract is UNCHANGED. Marker: desk-ourchat.
        children: [
          { path: '', name: 'desk-ourchat', component: { render: () => null },
            meta: { requiresAuth: true, title: 'OurChat' } },
          { path: ':id', name: 'desk-ourchat-thread', component: () => import('@/views/pocket/PocketOurStateThread.vue'), meta: { requiresAuth: true, title: 'OurChat' } },
        ],
      },
      {
        path: 'support',
        name: 'support',
        component: () => import('@/views/SupportView.vue'),
        meta: {
          requiresAuth: true,
          title: 'Support'
        }
      }
    ]
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFound.vue')
  }
]

// Create router instance
const router = createRouter({
  history: createWebHashHistory(),
  routes
})
// §FESUITE: a URL changed while the first navigation waits on the session restore (Back, a typed hash, a raw "#/"
// link) is carried out once the router listens; vue-router alone drops it (./missedFirstNavigation.ts)
replayLocationMissedBeforeReady(router)

// Navigation guards
router.beforeEach(async (to, from, next) => {
  import.meta.env.DEV && console.log('Router guard - navigating from', from.name, 'to', to.name)

  // ── POCKET BIOMETRIC LOCK (2026-07-25, Commander-found bypass) ──────────────────────────────
  // The lock used to be ONLY an overlay inside PocketShell. Pressing Android back navigated out
  // of the shell, unmounted the overlay, and dropped the user straight into advanced mode having
  // provided no biometric at all. An overlay you can navigate away from is decoration, not access
  // control — so the lock is enforced here, and the unlock happens in one place.
  // 2026-08-02 (Commander-found blackhole): "every route" overshot. A phone that had enrolled the
  // lock could no longer reach the LANDING PAGE or the blog — every public URL, even typed by
  // hand, bounced to the Pocket login. The lock protects the session's authority, not public
  // reading, so it now bites exactly where the auth system draws its own line: routes that
  // require a session. Public routes render for everyone; the Android-back bypass stays closed
  // because every advanced-mode route carries requiresAuth.
  if (pocketLockEngaged() && !to.path.startsWith('/pocket') && to.meta.requiresAuth) {
    return next({ path: '/pocket/home', replace: true })
  }

  // ── §POCKETBRIDGE2 P0.2 — a VISIT is not a choice. Batch 1 recorded
  // 'pocket' on any in-app walk into /pocket, so a desktop user peeking at
  // Pocket silently made it their login default. Only the explicit mode
  // controls record a preference now (setAdvanced in the pocket views,
  // the make-default toggle in More).

  const authStore = useAuthStore()
  const uiStore = useUIStore()

  // ── §FEFRAME W2 — the frame manifest before the first route ─────────────────────────────────────────────────
  // Who this registry is (and its peers, currencies, ledger sockets) is known before a view renders; past 4 s the
  // console proceeds in its honest identity-unknown state and fills in when the answer lands. Every later
  // navigation resolves at once (one promise per page).
  await whenFrameManifest(4000)

  // ── §COCKPIT P1 — per-registry feature routes ────────────────────────────────
  // A flag-gated surface must be unreachable, not merely unlisted: a hidden nav
  // item is not access control, and a typed URL is the first thing anyone tries.
  // Reads the SAME cached public-config promise the sidebar reads, so the guard
  // and the nav entry cannot disagree about whether this registry has the desk.
  // An unreadable config leaves every flag false — closed is the safe direction.
  if (to.meta.requiresRegistryFlag) {
    const cfg: Record<string, any> = await loadRegistryConfig()
    if (cfg[to.meta.requiresRegistryFlag as string] !== true) {
      // a public page's flag sends a visitor home, not to a dashboard that needs a login
      // §FESUITE: '/dashboard' was never a route, so a page switched off on this registry (/desk, /frame-kit) landed on
      // NotFound; it lands where the person's console starts instead.
      return next({ path: (to.meta.registryFlagRedirect as string) || homeRoute(), replace: true })
    }
  }
  // §MEMBERSHIP phase C: a page that opens where ANY of several settings of this registry holds its value (the registry
  // board: governance by membership, or a commons). The same cached config and the same safe direction as above: an
  // unreadable config holds no value, so the page stays closed.
  if (Array.isArray(to.meta.requiresRegistryAny)) {
    const cfg: Record<string, any> = await loadRegistryConfig()
    const open = (to.meta.requiresRegistryAny as [string, unknown][]).some(([k, v]) => cfg?.[k] === v)
    if (!open) return next({ path: homeRoute(), replace: true })
  }

  // ── FORCED PASSWORD CHANGE (§EXCISION-10) ────────────────────────────────────────
  // `must_change_password` has been enforced server-side for a long time — require_admin
  // 403s EVERY admin call until it clears — but nothing in the UI read it, so turning the
  // flag on gave the user an admin console where everything failed with no explanation.
  // That is why it was never set on credentials handed to a third party. This is the
  // missing half: while the flag is set, the ONLY reachable destinations are this screen
  // and logging out. Placed before the role/admin-flag routing below, because those
  // guards would otherwise send an admin to a dashboard whose every call 403s.
  if (
    authStore.isAuthenticated &&
    authStore.mustChangePassword &&
    to.name !== 'force-password-change' &&
    to.path !== '/login'
  ) {
    return next({ name: 'force-password-change', replace: true })
  }
  
  import.meta.env.DEV && console.log('Auth check:', {
    isAuthenticated: authStore.isAuthenticated,
    hasUser: !!authStore.user,
    hasToken: !!authStore.token,
    user: authStore.user,
    userRole: authStore.userRole
  })
  
  // Initialize auth if not already done
  if (!authStore.user && authStore.token) {
    import.meta.env.DEV && console.log('Initializing auth...')
    await authStore.initializeAuth()
  }
  
  // Public routes that should redirect if authenticated (excluding landing page)
  // §POCKETBRIDGE #PK23 (D2, F8): the destination is no longer hardwired to the
  // WebGL bridge — a saved mode choice wins, else phones get Pocket. This is
  // what makes the public chapter's "opens in Pocket mode on small screens"
  // TRUE instead of quietly false (F4).
  const publicAuthRoutes = ['login', 'register', 'forgot-password', 'reset-password']
  // §FESUITE: Settings' "Change password via recovery key" sends a signed-in person HERE on purpose
  // (?recovery=1); bouncing them home made the only password door in Settings do nothing at all.
  const changingWithRecoveryKey = to.name === 'forgot-password' && to.query.recovery === '1'
  if (publicAuthRoutes.includes(to.name as string) && authStore.isAuthenticated && !changingWithRecoveryKey) {
    const home = homeRoute()
    import.meta.env.DEV && console.log('Authenticated user on public route, redirecting to', home)
    return next({ path: home })
  }
  
  // Check if route requires authentication
  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    import.meta.env.DEV && console.log('Route requires auth but user not authenticated')
    // Save the intended destination
    return next({ 
      name: 'login', 
      query: { redirect: to.fullPath },
      replace: true
    })
  }
  
  // §FESUITE: a session restore still in flight may yet grant the role; refuse only once it has settled
  if ((to.meta.requiresRole || to.meta.requiresAdminFlag) && authStore.authSettling()) {
    await authStore.authSettling()
  }

  // Check role requirements
  if (to.meta.requiresRole) {
    const requiredRole = to.meta.requiresRole as string
    import.meta.env.DEV && console.log('checkAuth:', {
      requiredRole,
      userRole: authStore.userRole,
      hasRole: authStore.checkAuth(requiredRole),
      user: authStore.user
    })
    if (!authStore.checkAuth(requiredRole)) {
      import.meta.env.DEV && console.log('User lacks required role:', requiredRole, 'User role:', authStore.userRole)
      
      // Show user-friendly notification about access restriction
      const routeName = to.name as string
      const friendlyNames: Record<string, string> = {
        'federation': 'Federation',
        'admin-panel': 'Admin Panel'
      }
      
      // D6-846: the page by its readable title (the route's slug read "admin-emission-policy requires admin privileges")
      const pageName = (to.meta.title as string) || friendlyNames[routeName] || 'This page'
      uiStore.showNotification({
        type: 'warning',
        title: 'Access Restricted',
        message: `${pageName} requires ${requiredRole} privileges. Your current role is: ${authStore.userRole || 'user'}`
      })
      
      // A click from an open page stays on it. D6-846: a link opened directly has no page behind it (the router sat at /
      // with an almost empty page): it goes where the person's console starts, as the agent refusals below do.
      return from.matched.length ? next(false) : next(homeRoute())
    }
  }

  // RBAC §65 (2026-05-08): granular sub-flag hard gate.
  // `requiresRole: 'admin'` accepts any admin (super-or-any-flag, post-§60
  // checkAuth fix). The new `requiresAdminFlag` adds a SECOND check for
  // the specific sub-flag the route declares — so a treasury-only admin
  // direct-URL'ing to /admin/agents (which needs `platform`) is now
  // redirected to /mission-control with a clear toast, instead of landing
  // on the page and seeing 403 toasts on every API call. Super-flag
  // (is_admin=true) passes every sub-flag check via usePermissions
  // short-circuit, so Commander operators see no behavior change.
  if (to.meta.requiresAdminFlag) {
    const flag = to.meta.requiresAdminFlag as AdminAction
    if (!usePermissions().can(flag)) {
      log.debug('Route requires admin sub-flag', flag, '— user lacks it')
      uiStore.showNotification({
        type: 'warning',
        title: 'Access Restricted',
        message: `This area requires admin_${flag} privileges.`,
      })
      return next({ name: 'mission-control' })
    }
  }

  // §pass66 (2026-05-22) — Mainframe-only route gate. Routes with
  // `meta.requiresMainframe: true` redirect cloud-op users to
  // mission-control with a clear toast. Same gating as the backend's
  // `require_mainframe_only` dep so frontend + backend agree on policy.
  if (to.meta.requiresMainframe) {
    const mf = useMainframe()
    // §FEFRAME W2: the manifest was awaited at the top of this guard, so the answer is the server's (the old 1 s
    // poll could redirect a mainframe admin on a cold boot, and let an operator through on a slow one).
    if (!mf.ready.value) await mf.refetch()
    if (!mf.isMainframe.value && mf.readFailed.value) {
      // §FESUITE (2026-10-09): no source answered. Closed, as the safe side, but never "you are on a cloud-op": the
      // console reads again on its own and the next navigation asks once more.
      log.debug('Route requires mainframe — the registry could not be read; redirected without a verdict')
      uiStore.showNotification({
        type: 'warning',
        title: 'Could not check this view',
        message: 'Whether this registry offers this view could not be read just now. Try again in a moment.',
      })
      return next({ name: 'mission-control' })
    }
    if (!mf.isMainframe.value) {
      log.debug('Route requires mainframe — cloud-op redirected')
      uiStore.showNotification({
        type: 'info',
        title: 'Mainframe-only feature',
        message: 'This view runs on sovereign mainframes only — cloud-ops federate with the mainframe for these actions.',
      })
      return next({ name: 'mission-control' })
    }
  }

  // Check session expiry
  if (authStore.isAuthenticated && authStore.isSessionExpired) {
    import.meta.env.DEV && console.log('Session expired, attempting refresh...')
    // Try to refresh the session
    const refreshed = await authStore.refreshSession()
    if (!refreshed) {
      return next({ 
        name: 'login', 
        query: { expired: 'true' },
        replace: true
      })
    }
  }
  
  // Check if route requires an active agent
  if (to.meta.requiresAgent && (authStore.isDeveloper || authStore.isAdmin)) {
    import.meta.env.DEV && console.log('Route requires agent, checking...')
    
    // Ensure agents are loaded, and wait for a load already in flight (it restores the saved agent)
    if (authStore.availableAgents.length === 0 || authStore.agentLoading) {
      await authStore.fetchAvailableAgents()
    }
    
    // Check if we have an active agent
    if (!authStore.activeAgent || !authStore.agentToken) {
      import.meta.env.DEV && console.log('No active agent, checking available agents...')
      
      // The agents this console can act as. §FESUITE (2026-10-10): the store's own rule (canActAs: an agent you own on
      // this registry needs no saved secret, §FEFRAME W3), not only "a secret is saved here". An owned agent whose sign-in
      // failed while the registry did not answer fell to "none has its credentials stored here" with the create sheet
      // open, and the sheet stayed open once the registry was back (sweeps/recovery: five agent pages on V0589).
      const agentsWithCredentials = authStore.availableAgents.filter(
        (agent: any) => !cannotActReason(agent)   // §MCPTEST30 (V0640): a revoked or suspended agent offers nothing
          && (agent.hasCredentials || (agent.client_id && agent.client_secret) || !!authStore.canActAs?.(agent))
      )

      if (agentsWithCredentials.length > 0) {
        // We have agents with credentials but none selected — pulse the
        // AgentSwitcher in the top-right + auto-open it (RBAC §66, 2026-05-08).
        // Replaces the pre-§66 UX where users got a generic toast and had
        // to find the picker themselves. Stay on current page so they
        // don't lose context.
        authStore.showAgentSelector = true
        uiStore.pulseAgentSwitcher()
        if (authStore.agentSignInWasAnOutage?.()) {
          // the saved agent's sign-in had no answer (none, or a server error): the store tries again by itself
          uiStore.showWarning(
            'Your agent could not sign in just now',
            'The registry did not answer. The console tries again by itself; pick the agent from the top-right to try now.',
          )
        } else {
          uiStore.showWarning(
            'Active Agent Required',
            'Pick an agent from the top-right to continue.',
          )
        }
        // §FESUITE: aborting the FIRST navigation (a cold deep link) leaves no page at all; go home with the picker open
        return from.matched.length ? next(false) : next(homeRoute())
      } else if (authStore.availableAgents.length > 0) {
        // We have agents but none have credentials (backend test agents)
        uiStore.showWarning(
          'No agent can act in this browser yet',
          'This page acts as one of your agents, and none has its credentials stored here. Import them from the agent switcher (Bulk Import), reset them in My Agents, or create a wallet agent here.'
        )
        // §WALLETAGENT (2026-09-02) — home (Pocket or the dashboard, by the landing decision) with the
        // quick-create modal open in wallet mode, instead of a bounce to AgentForge with a toast.
        uiStore.openQuickAgentModal()
        return next(homeRoute())
      } else if (authStore.agentFetchFailed) {
        // §FESUITE (V0577): the agents read failed, which is not "no agents". This fell through to "No wallet agent yet …
        // Create your wallet agent first" with the create sheet open, for a member whose agents could not be read. The
        // selector says the read failed and reads again (AgentSelectorModal); the person stays where they were.
        authStore.showAgentSelector = true
        uiStore.showWarning(
          'Your agents could not be read',
          'This page acts as one of your agents, and they could not be read just now. Try again in the agent picker.'
        )
        return from.matched.length ? next(false) : next(homeRoute())
      } else {
        // No agents at all, redirect to onboarding or agent creation
        uiStore.showInfo(
          'No wallet agent yet',
          'This acts as one of your agents. Create your wallet agent first: it takes a name and a minute.'
        )
        // §WALLETAGENT (2026-09-02) — home (Pocket or the dashboard, by the landing decision) with the
        // quick-create modal open in wallet mode, instead of a bounce to AgentForge with a toast.
        uiStore.openQuickAgentModal()
        return next(homeRoute())
      }
    }
  }
  
  import.meta.env.DEV && console.log('Navigation allowed')
  next()
})

// After navigation hook for analytics, etc.
router.afterEach((to, from) => {
  // Update document title: `<view> | <this registry's name>` (§FEFRAME W2: the name its manifest states; the fixed
  // "The Protocol Registry" suffix named no frame at all)
  const who = currentFrameManifest()?.self?.display_name || 'TheProtocol'
  const title = to.meta.title || to.name || who
  document.title = `${String(title)} | ${who}`
  
  // Scroll to top on navigation
  window.scrollTo(0, 0)
})

// Handle router errors — particularly stale-chunk failures after a deploy (services/staleChunk.ts holds the rule; the error
// boundary answers a component's stale chunk with it too, §FESUITE 2026-10-10).
router.onError((error) => {
  console.error('Router error:', error)
  if (!isStaleChunkError(error)) return
  recoverFromStaleChunk(log)
})

// A successful navigation means the fresh bundle loaded cleanly — reset the
// consecutive-failure counter so a future deploy gets its full retry budget.
router.afterEach(() => { staleChunkRecovered() })

// Export router setup function  
export function setupRouterGuards(routerInstance: Router) {
  // Additional guard setup can be added here
}

export default router
