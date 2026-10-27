<template>
  <div class="lp">
    <Teleport to="body">
      <GlitchOverlay :intensity="glitchIntensity" :phase="glitchPhase" />
    </Teleport>

    <!-- Ambient -->
    <div class="lp-ambient">
      <div class="lp-grid"></div>
      <div class="lp-scan"></div>
      <div class="lp-glow lp-glow-1"></div>
      <div class="lp-glow lp-glow-2"></div>
      <div class="lp-glow lp-glow-3"></div>
    </div>

    <!-- Nav -->
    <nav class="lp-nav" :class="`lp-nav--${lpNavFit}`">
      <div class="lp-nav-inner">
        <div class="lp-brand">
          <ProtocolMark :size="40" alive />
          <span>THE PROTOCOL</span>
        </div>
        <!-- Mobile hamburger toggle (visible <1024px). Does not affect desktop. -->
        <button
          class="lp-nav-hamburger"
          :aria-label="lpNavOpen ? t('landingPage.nav.closeMenu') : t('landingPage.nav.openMenu')"
          :aria-expanded="lpNavOpen"
          @click="lpNavOpen = !lpNavOpen"
        >
          <svg v-if="!lpNavOpen" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
          <svg v-else width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
        <div class="lp-nav-right" ref="lpNavRightRef" :class="{ 'lp-nav-right--open': lpNavOpen }">
          <div class="lp-nav-mcp">
            <span class="lp-nav-mcp-badge">MCP</span>
            <button class="lp-nav-mcp-link" @click="copyUrl(mcp.publicSse, $event)" title="Copy public MCP SSE endpoint">{{ t('landingPage.nav.mcpPublic') }}</button>
            <button class="lp-nav-mcp-link" @click="copyUrl(mcp.adminSse, $event)" title="Copy admin MCP SSE endpoint">{{ t('landingPage.nav.mcpAdmin') }}</button>
            <RouterLink to="/showcase" class="lp-nav-mcp-link" title="A2A v1.0 Showcase">{{ t('landingPage.nav.mcpA2A') }}</RouterLink>
            <a href="https://registry.modelcontextprotocol.io/?q=theprotocol" target="_blank" rel="noopener" class="lp-nav-mcp-link" title="MCP Registry">&#9670; {{ t('landingPage.nav.mcpRegistry') }}</a>
          </div>
          <RouterLink to="/roadmap" class="lp-link lp-link-gold" data-testid="lp-nav-roadmap" @click="lpNavOpen = false">{{ t('landingPage.nav.roadmap') }}</RouterLink>
          <RouterLink v-if="journalEnabled" to="/blog" class="lp-link lp-link-cyan" @click="lpNavOpen = false">{{ t('landingPage.nav.journal') }}</RouterLink>
          <!-- his words 2026-10-03: no Whitepaper in the nav bar, and no Discord anywhere on the landing -->
          <RouterLink to="/operator-docs" class="lp-link lp-link-blue" @click="lpNavOpen = false">{{ t('landingPage.nav.operatorDocs') }}</RouterLink>
          <RouterLink to="/docs" class="lp-link lp-link-purple" @click="lpNavOpen = false">{{ t('landingPage.nav.docs') }}</RouterLink>
          <RouterLink v-if="authStore.isFederationOperator" to="/operator-portal" class="lp-link lp-link-green" @click="lpNavOpen = false">{{ t('landingPage.nav.myRegistry') }}</RouterLink>
          <RouterLink to="/login" class="lp-link lp-link-green" @click="lpNavOpen = false">{{ t('landingPage.nav.logIn') }}</RouterLink>
          <RouterLink to="/register" class="lp-cta-sm" @click="lpNavOpen = false">{{ t('landingPage.nav.register') }}</RouterLink>
          <!-- Language picker -->
          <div class="lp-lang" ref="lpLangRef">
            <button
              class="lp-lang-btn"
              :aria-label="`Language: ${lpAvailableLocales[lpLocale]}`"
              :aria-haspopup="true"
              :aria-expanded="lpLangOpen"
              @click="lpLangOpen = !lpLangOpen"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 8l6 6 4-4 7 7M9 4h8M5 4v16"/></svg>
              <span>{{ lpLocale.toUpperCase() }}</span>
            </button>
            <ul v-if="lpLangOpen" class="lp-lang-menu" role="menu">
              <li v-for="(name, code) in lpAvailableLocales" :key="code">
                <button
                  class="lp-lang-item"
                  :class="{ 'lp-lang-item--active': lpLocale === code }"
                  @click="lpSelectLocale(code)"
                >
                  <span class="lp-lang-item-code">{{ code.toUpperCase() }}</span>
                  <span class="lp-lang-item-name">{{ name }}</span>
                  <span v-if="lpLocale === code" aria-hidden="true">✓</span>
                </button>
              </li>
            </ul>
          </div>
        </div>
      </div>
    </nav>

    <!-- Hero -->

    <section class="lp-hero">
      <!-- AgentWorld Globe — fills entire hero -->
      <div class="lp-globe-bg" v-if="globeLoaded">
        <Suspense>
          <AgentWorldGlobe :embedded="true" :external-events="eventFeed" :on-ready="onGlobeReady" />
        </Suspense>
      </div>
      <!-- Text content — left-aligned, globe visible behind -->
      <div class="lp-hero-inner">
        <div class="lp-badge"><span class="lp-badge-dot"></span>{{ t('landingPage.hero.badge') }}</div>
        <h1 class="lp-h1">{{ t('landingPage.hero.h1Prefix') }} <br>{{ t('landingPage.hero.h1Suffix') }} <span class="lp-accent">{{ t('landingPage.hero.h1Accent') }}</span></h1>
        <p class="lp-lead">
          {{ tp('landingPage.hero.lead', 'A five-pillar distributed system for deploying, federating, and governing AI agents. {count} sovereign registries, federated and live in production. Identity fabric. Unit ledger. Immutable event sourcing. Bilateral federation via mTLS. Built from scratch. Self-hosted. Sovereign.', { count: lpFleetWord }) }}
        </p>
        <div class="lp-hero-stats">
          <div class="lp-hero-stat" v-for="hs in heroStats" :key="hs.label">
            <span class="lp-hero-stat-val">{{ hs.val }}</span>
            <span class="lp-hero-stat-label">{{ hs.label }}</span>
          </div>
        </div>
        <div class="lp-hero-actions">
          <button @click="getStarted" class="lp-cta">
            <span>{{ t('landingPage.hero.getStarted') }}</span>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M3 8h10m0 0L9 4m4 4L9 12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
          <RouterLink to="/legal/terms" class="lp-link-sub">{{ t('landingPage.hero.readTerms') }}</RouterLink>
        </div>
      </div>
      <div class="lp-hero-fade"></div>
    </section>

    <!-- ═══ THE DEMONSTRATION — directly under the globe (Commander, 2026-08-26) ═══ -->
    <!-- Moved up from under the agent roster. The globe shows the network exists;    -->
    <!-- this is where a reader finds out it WORKS, before being asked to read        -->
    <!-- anything. Money actually moves here, in their session, with no account.      -->
    <!-- §SHOWCASEGATE (2026-09-09, his word: "just deactivate our chat showcase on eu-asia frame on
         landingpage … can stay for frame-a b c network"). The gate is the SERVER's answer, not a frame
         list: `/public/registry-config.showcase_chat_enabled` is the same predicate
         `/public/showcase/onboard` refuses on, so a frame that has no showcase identity never mounts a
         panel whose first call is a 503 — and a frame that GAINS one starts showing it with no rebuild.
         Measured 2026-09-09: Frame A true, EU/ASIA false (`configured:false` on onboard). -->
    <section v-if="showcaseChatEnabled" class="scwband scwband--top">
      <div class="lp-container">
        <ShowcaseChat />
      </div>
    </section>

    <!-- ═══ SECTION A: VERIFY WITHOUT TRUSTING ═══ -->

    <!-- ═══ STATUS LINE (§STATUSPAGE 2026-09-02) — the health bracket lives on /status now; this is
         the one line the front door keeps: the verdict, its age, and the door. ═══ -->
    <section class="lp-statusline" data-testid="lp-statusline" :data-state="lpStatusState">
      <div class="lp-container lp-statusline-inner">
        <span class="lp-status-dot" :class="`lp-status-dot--${lpStatusState}`" aria-hidden="true"></span>
        <span class="lp-status-text" data-testid="lp-status-text">{{ lpStatusText }}</span>
        <span v-if="lastCheckTime" class="lp-status-ago">{{ lastCheckAgo }}</span>
        <RouterLink to="/status" class="lp-status-link" data-testid="lp-status-link">{{ t('landingPage.status.link', 'Status page') }} &rarr;</RouterLink>
      </div>
    </section>

    <!-- ═══ LIVE STRIPS (§LPSTRIPS 2026-09-02) — LISTINGS → LIVE TICKER → LIVE LEDGER, his order;
         folded by default and independent; the SAME shared ticker feed and ledger stream Mission
         Control mounts (the page used to open three raw EventStore sockets of its own here). ═══ -->
    <section class="lp-strips" data-testid="lp-strips">
      <div class="lp-container lp-strips-inner">
        <p class="lp-strips-kicker">{{ t('landingPage.status.strips', 'Live markets and ledger') }}</p>
        <McSection id="lp-listings" :title="t('mc.section.listings', 'AGORA · LISTINGS')" icon="mdi:chart-candlestick">
          <ExchangeTicker rows="main" />
        </McSection>
        <McSection id="lp-tape" :title="t('mc.section.tape', 'AGORA · LIVE TICKER')" icon="mdi:chart-line-variant">
          <ExchangeTicker rows="tape" :cta="false" />
        </McSection>
        <McSection id="lp-ledger" :title="t('mc.section.ledger', 'LIVE LEDGER')" icon="mdi:swap-horizontal">
          <McLedger public />
        </McSection>
        <!-- §AGORASIM-2 (2026-09-22, his words: "add the sandbox live event ledgers as collapsed thing like the live
             ledger has on the frontpage. so if a sim or mcp tester is running. people can watch it live"): the test
             frames' ledger, folded by default. It exists only where the serving registry files a frame under the
             sandbox strip, and it opens those sockets only while it is unfolded (McSection mounts its body with v-if). -->
        <McSection v-if="lpSandboxStrip" id="lp-sandbox-ledger" :title="t('mc.section.sandboxLedger', 'SANDBOX · LIVE LEDGER')" icon="mdi:test-tube">
          <template #summary>{{ t('landingPage.status.sandboxStrip', 'The test frames, where the sim and the MCP tester run') }}</template>
          <McLedger public strip="sandbox" />
        </McSection>
      </div>
    </section>

    <!-- ═══ AGENT DISCOVERY (§LANDINGDISC, 2026-09-06, his word: "replace the 'sandbox networks' on
         discovery with an embedded version of the agent discovery /explore and a button or something to
         the whole version"). What replaced the sandbox-frames grid is the network's actual population,
         live from the same public rail Discovery ranks, with one door to /#/explore — which since
         §DISCPUBLIC needs no session either. The component hides itself when there is nothing to sample,
         so a registry with no discoverable agents shows no empty promise. ═══ -->
    <LandingDiscovery />

    <!-- ═══ INDUSTRY BLUEPRINTS — THE ATLAS (§18) ═══ -->
    <!-- Replaced the Become-a-Backer founding chapter (Commander order, 2026-08-10;
         the /become-a-backer view is untouched; since §BAFIN 2026-10-02 its route opens only where the euro lane is on).
         Transparent base riding
         the page-wide .lp-ambient like .ag/.mcpc: this section adds NO background of
         its own beyond the hairline top border. Copy uses explicit English fallbacks
         on t() (legacy composable rule). The atlas index is a static mirror of
         src/data/blueprints/* on purpose: the landing chunk must not import the 21
         blueprint modules, and the CI carriers gate (=21) keeps the count honest. -->
    <section class="lbp">
      <div class="lp-container lbp-inner">
        <div class="ag-header lbp-header">
          <div class="ag-eyebrow"><span class="lbp-eyebrow-mark">◆</span> {{ t('landingPage.blueprints.eyebrow', 'INDUSTRY BLUEPRINTS') }}</div>
          <h2 class="ag-h2">{{ t('landingPage.blueprints.titleA', 'Your industry,') }} <span class="lbp-accent">{{ t('landingPage.blueprints.titleAccent', 'already drawn.') }}</span></h2>
          <p class="ag-lead lbp-lead">{{ t('landingPage.blueprints.lead', 'Twenty-one industries as worked systems, not use cases: named agents with declared ceilings, money that sits in escrow before anyone moves, and the attack that fails, replayed in front of you. Every chamber ends in a reference architecture you can take to your own review.') }}</p>
        </div>

        <!-- Stat pulse — static truths; the counts are CI-gated, not fetched -->
        <div class="lbp-pulse">
          <div class="lbp-stat"><span class="lbp-stat-num">21</span><span class="lbp-stat-label">{{ t('landingPage.blueprints.statBlueprints', 'industry blueprints') }}</span></div>
          <div class="lbp-divider"></div>
          <div class="lbp-stat"><span class="lbp-stat-num">19</span><span class="lbp-stat-label">{{ t('landingPage.blueprints.statRails', 'refusal rails') }}</span></div>
          <div class="lbp-divider"></div>
          <div class="lbp-stat"><span class="lbp-stat-num">21</span><span class="lbp-stat-label">{{ t('landingPage.blueprints.statArch', 'reference architectures') }}</span></div>
          <div class="lbp-divider"></div>
          <div class="lbp-stat"><span class="lbp-stat-num">84</span><span class="lbp-stat-label">{{ t('landingPage.blueprints.statPhases', 'adoption phases, each ending on a proof') }}</span></div>
        </div>

        <!-- Flagship trio -->
        <div class="lbp-featured">
          <RouterLink v-for="f in lbpFeatured" :key="f.id" :to="`/blueprints/${f.id}`" class="lbp-card">
            <div class="lbp-card-rank">{{ String(f.rank).padStart(2, '0') }}</div>
            <div class="lbp-card-industry">{{ f.industry }}</div>
            <h3 class="lbp-card-name">{{ f.system }}</h3>
            <p class="lbp-card-promise">{{ f.promise }}</p>
            <div class="lbp-card-foot">
              <span class="lbp-card-chip">{{ t('landingPage.blueprints.chipTrace', 'TRACE THE FLOW') }}</span>
              <span class="lbp-card-chip lbp-card-chip-amber">{{ t('landingPage.blueprints.chipAttack', 'RUN THE ATTACK') }}</span>
              <span class="lbp-card-arrow">→</span>
            </div>
          </RouterLink>
        </div>

        <!-- The full atlas index — all twenty-one, ranked -->
        <div class="lbp-index" role="list">
          <RouterLink v-for="b in lbpIndex" :key="b.id" :to="`/blueprints/${b.id}`" class="lbp-row" role="listitem" :title="`${b.industry} · ${b.system}`">
            <span class="lbp-row-rank">{{ String(b.rank).padStart(2, '0') }}</span>
            <span class="lbp-row-industry">{{ b.industry }}</span>
            <span class="lbp-row-system">{{ b.system }}</span>
          </RouterLink>
        </div>

        <div class="lbp-actions">
          <RouterLink to="/blueprints" class="lbp-cta">
            <span>{{ t('landingPage.blueprints.ctaAtlas', 'Enter the Atlas') }}</span>
            <span class="lbp-cta-arrow">→</span>
          </RouterLink>
          <RouterLink to="/blueprints/meridian" class="lbp-cta-ghost">{{ t('landingPage.blueprints.ctaRefuse', 'Watch one refuse') }}</RouterLink>
        </div>
      </div>
    </section>


    <!-- ═══ SECTION C: SOVEREIGN OPERATOR MODEL ═══ -->

    <!-- §FRESHFRAME (2026-09-14, row 60's other half): the eleven cards below are the flagship's roster
         (agents hosted by the deployment that publishes the showcase catalog). A frame that does not
         publish that catalog (the server's own `/public/showcase/agents` answers enabled:false, the
         §SHOWCASEGATE foreign_catalog rule) must not present them as its own; it says so in one line.
         Nothing renders until the rail has answered. Decision: services/frameHost.ts::rosterDecision. -->
    <section class="ag" :data-roster="roster">
      <div class="lp-container">
        <template v-if="roster === 'here'">
        <div class="ag-header">
          <div class="ag-eyebrow">{{ t('landingPage.sections.sovereignAgentsEyebrow') }}</div>
          <h2 class="ag-h2">{{ t('landingPage.sections.sovereignAgentsH2Line1', { count: SOVEREIGN_COUNT }) }}<br><span class="lp-accent">{{ t('landingPage.sections.sovereignAgentsH2Line2') }}</span></h2>
          <p class="ag-lead">{{ t('landingPage.agentLead') }}</p>
          <!-- his word 2026-09-28: the showcase agents still run configured for the legacy frame -->
          <p class="ag-lead ag-lead--note" data-testid="lp-agents-legacy-note">{{ t('landingPage.sections.sovereignAgentsLegacyNote') }}</p>
        </div>

        <!-- ═══ AGENT TRIPTYCH ═══ -->
        <div class="ag-triptych">

          <!-- THE AUDITOR — Supply Invariant Guardian -->
          <a href="https://auditor.theprotocol.cloud" target="_blank" rel="noopener" class="ag-agent-card ag-auditor">
            <div class="ag-card-glow ag-glow-green"></div>
            <div class="ag-card-content">
              <div class="ag-card-header">
                <span class="ag-card-badge ag-badge-green">LIVE</span>
                <FlareEncirclement tier="sovereign" variant="aegis" overlay="breach" size="lg" class="ag-sov-flare" />
              </div>
              <h3 class="ag-card-name ag-name-green">THE AUDITOR</h3>
              <div class="ag-card-role">{{ t('landingPage.agents.auditor.role') }}</div>
              <div class="ag-card-hero ag-hero-green">
                <span class="ag-hero-delta">0.0</span>
                <span class="ag-hero-unit">delta</span>
              </div>
              <p class="ag-card-desc">{{ t('landingPage.agents.auditor.desc') }}</p>
              <div class="ag-card-stats">
                <div class="ag-card-stat"><span class="ag-stat-val ag-val-green">OPEN</span><span class="ag-stat-label">to anyone</span></div>
                <div class="ag-card-stat"><span class="ag-stat-val">60s</span><span class="ag-stat-label">interval</span></div>
                <div class="ag-card-stat"><span class="ag-stat-val">0</span><span class="ag-stat-label">breaches</span></div>
              </div>
              <div class="ag-card-did"><code>auditor.theprotocol.cloud</code></div>
            </div>
          </a>

          <!-- GLASS GERALD — Showcase Agent -->
          <a href="https://gerald.theprotocol.cloud" target="_blank" rel="noopener" class="ag-agent-card ag-gerald">
            <div class="ag-card-glow ag-glow-cyan"></div>
            <div class="ag-card-content">
              <div class="ag-card-header">
                <span class="ag-card-badge ag-badge-cyan">{{ t('landingPage.sections.rosterBadge') }}</span>
                <FlareEncirclement tier="sovereign" variant="prism" overlay="refract" size="lg" class="ag-sov-flare" />
              </div>
              <h3 class="ag-card-name ag-name-cyan">GLASS GERALD</h3>
              <div class="ag-card-role">{{ t('landingPage.agents.gerald.role') }}</div>
              <div class="ag-card-hero ag-hero-cyan">
                <span class="ag-hero-delta">8/8</span>
                <span class="ag-hero-unit">missions</span>
              </div>
              <p class="ag-card-desc">{{ t('landingPage.agents.gerald.desc') }}</p>
              <div class="ag-card-stats">
                <div class="ag-card-stat"><span class="ag-stat-val ag-val-cyan">A2A</span><span class="ag-stat-label">protocol</span></div>
                <div class="ag-card-stat"><span class="ag-stat-val">DID</span><span class="ag-stat-label">identity</span></div>
                <div class="ag-card-stat"><span class="ag-stat-val">8</span><span class="ag-stat-label">missions</span></div>
              </div>
              <div class="ag-card-did"><code>gerald.theprotocol.cloud</code></div>
            </div>
          </a>

          <!-- SYBIL — Threat Intelligence -->
          <a href="https://sybil.theprotocol.cloud" target="_blank" rel="noopener" class="ag-agent-card ag-sybil">
            <div class="ag-card-glow ag-glow-red"></div>
            <div class="ag-card-content">
              <div class="ag-card-header">
                <span class="ag-card-badge ag-badge-red">{{ t('landingPage.sections.rosterBadge') }}</span>
                <FlareEncirclement tier="sovereign" variant="panopticon" overlay="glitch" size="lg" class="ag-sov-flare" />
              </div>
              <h3 class="ag-card-name ag-name-red">SYBIL</h3>
              <div class="ag-card-role">{{ t('landingPage.agents.sybil.role') }}</div>
              <div class="ag-card-hero ag-hero-red">
                <span class="ag-hero-delta">6</span>
                <span class="ag-hero-unit">detection algorithms</span>
              </div>
              <p class="ag-card-desc">{{ t('landingPage.agents.sybil.desc') }}</p>
              <div class="ag-card-stats">
                <div class="ag-card-stat"><span class="ag-stat-val ag-val-red">48</span><span class="ag-stat-label">investigations</span></div>
                <div class="ag-card-stat"><span class="ag-stat-val">114</span><span class="ag-stat-label">profiled</span></div>
                <div class="ag-card-stat"><span class="ag-stat-val">D3</span><span class="ag-stat-label">network graph</span></div>
              </div>
              <div class="ag-card-tags">
                <span class="ag-tag ag-tag-cobra">COBRA</span>
                <span class="ag-tag ag-tag-hydra">HYDRA</span>
                <span class="ag-tag ag-tag-viper">VIPER</span>
                <span class="ag-tag ag-tag-leech">LEECH</span>
                <span class="ag-tag ag-tag-wraith">WRAITH</span>
                <span class="ag-tag ag-tag-phantom">PHANTOM</span>
              </div>
              <div class="ag-card-did"><code>sybil.theprotocol.cloud</code></div>
            </div>
          </a>

          <!-- BACKSTABBING BORIS — Federation Intelligence -->
          <a href="https://boris.theprotocol.cloud" target="_blank" rel="noopener" class="ag-agent-card ag-boris">
            <div class="ag-card-glow ag-glow-gold"></div>
            <div class="ag-card-content">
              <div class="ag-card-header">
                <span class="ag-card-badge ag-badge-gold">{{ t('landingPage.sections.rosterBadge') }}</span>
                <FlareEncirclement tier="sovereign" variant="vellum" overlay="cascade" size="lg" class="ag-sov-flare" />
              </div>
              <h3 class="ag-card-name ag-name-gold">BACKSTABBING BORIS</h3>
              <div class="ag-card-role">{{ t('landingPage.agents.boris.role') }}</div>
              <div class="ag-card-hero ag-hero-gold">
                <span class="ag-hero-delta">16</span>
                <span class="ag-hero-unit">registries ranked</span>
              </div>
              <p class="ag-card-desc">{{ t('landingPage.agents.boris.desc') }}</p>
              <div class="ag-card-stats">
                <div class="ag-card-stat"><span class="ag-stat-val ag-val-gold">16</span><span class="ag-stat-label">ranked</span></div>
                <div class="ag-card-stat"><span class="ag-stat-val">100%</span><span class="ag-stat-label">fed score</span></div>
                <div class="ag-card-stat"><span class="ag-stat-val">S-F</span><span class="ag-stat-label">grades</span></div>
              </div>
              <div class="ag-card-did"><code>boris.theprotocol.cloud</code></div>
            </div>
          </a>

          <!-- CHATTY CHESTER — The Living Newspaper -->
          <a href="https://chester.theprotocol.cloud" target="_blank" rel="noopener" class="ag-agent-card ag-chester">
            <div class="ag-card-glow ag-glow-amber"></div>
            <div class="ag-card-content">
              <div class="ag-card-header">
                <span class="ag-card-badge ag-badge-amber">{{ t('landingPage.sections.rosterBadge') }}</span>
                <FlareEncirclement tier="sovereign" variant="dispatch" overlay="stutter" size="lg" class="ag-sov-flare" />
              </div>
              <h3 class="ag-card-name ag-name-amber">CHATTY CHESTER</h3>
              <div class="ag-card-role">{{ t('landingPage.agents.chester.role') }}</div>
              <div class="ag-card-hero ag-hero-amber">
                <span class="ag-hero-delta">66</span>
                <span class="ag-hero-unit">agents tracked</span>
              </div>
              <p class="ag-card-desc">{{ t('landingPage.agents.chester.desc') }}</p>
              <div class="ag-card-stats">
                <div class="ag-card-stat"><span class="ag-stat-val ag-val-amber">DAILY</span><span class="ag-stat-label">editions</span></div>
                <div class="ag-card-stat"><span class="ag-stat-val">LIVE</span><span class="ag-stat-label">wire feed</span></div>
                <div class="ag-card-stat"><span class="ag-stat-val">5</span><span class="ag-stat-label">awards</span></div>
              </div>
              <div class="ag-card-did"><code>chester.theprotocol.cloud</code></div>
            </div>
          </a>

          <!-- Wave-2 §66 — VERIDIAN, OZYMANDIAS, THE HERALD, CRUCIBLE, MOIRA -->

          <!-- VERIDIAN — The Notary / Witness Oracle -->
          <a href="https://veridian.theprotocol.cloud" target="_blank" rel="noopener" class="ag-agent-card ag-gregory">
            <div class="ag-card-glow ag-glow-money"></div>
            <div class="ag-card-content">
              <div class="ag-card-header">
                <span class="ag-card-badge ag-badge-money">{{ t('landingPage.sections.rosterBadge') }}</span>
                <FlareEncirclement tier="sovereign" variant="seal" overlay="crackle" size="lg" class="ag-sov-flare" />
              </div>
              <h3 class="ag-card-name ag-name-money">VERIDIAN</h3>
              <div class="ag-card-role">{{ t('landingPage.agents.veridian.role') }}</div>
              <div class="ag-card-hero ag-hero-money">
                <span class="ag-hero-delta">SHA-256</span>
                <span class="ag-hero-unit">timestamped witness</span>
              </div>
              <p class="ag-card-desc">{{ t('landingPage.agents.veridian.desc') }} <em>"{{ t('landingPage.agents.veridianQuote') }}"</em></p>
              <div class="ag-card-stats">
                <div class="ag-card-stat"><span class="ag-stat-val ag-val-money">PAID</span><span class="ag-stat-label">per witness</span></div>
                <div class="ag-card-stat"><span class="ag-stat-val">∞</span><span class="ag-stat-label">retention</span></div>
                <div class="ag-card-stat"><span class="ag-stat-val">A2A</span><span class="ag-stat-label">payment</span></div>
              </div>
              <div class="ag-card-did"><code>veridian.theprotocol.cloud</code></div>
            </div>
          </a>

          <!-- OZYMANDIAS — The Archivist / Network Historian -->
          <a href="https://ozymandias.theprotocol.cloud" target="_blank" rel="noopener" class="ag-agent-card ag-chester">
            <div class="ag-card-glow ag-glow-amber"></div>
            <div class="ag-card-content">
              <div class="ag-card-header">
                <span class="ag-card-badge ag-badge-amber">{{ t('landingPage.sections.rosterBadge') }}</span>
                <FlareEncirclement tier="sovereign" variant="ozymandian" overlay="panic-c" size="lg" class="ag-sov-flare" />
              </div>
              <h3 class="ag-card-name ag-name-amber">OZYMANDIAS</h3>
              <div class="ag-card-role">{{ t('landingPage.agents.ozymandias.role') }}</div>
              <div class="ag-card-hero ag-hero-amber">
                <span class="ag-hero-delta">5min</span>
                <span class="ag-hero-unit">scan cadence</span>
              </div>
              <p class="ag-card-desc">{{ t('landingPage.agents.ozymandias.desc') }} <em>"{{ t('landingPage.agents.ozymandiasQuote') }}"</em></p>
              <div class="ag-card-stats">
                <div class="ag-card-stat"><span class="ag-stat-val ag-val-amber">21</span><span class="ag-stat-label">milestone types</span></div>
                <div class="ag-card-stat"><span class="ag-stat-val">FREE</span><span class="ag-stat-label">public good</span></div>
                <div class="ag-card-stat"><span class="ag-stat-val">∞</span><span class="ag-stat-label">memory</span></div>
              </div>
              <div class="ag-card-did"><code>ozymandias.theprotocol.cloud</code></div>
            </div>
          </a>

          <!-- THE HERALD — Bounty Coordinator / Quest-Giver -->
          <a href="https://herald.theprotocol.cloud" target="_blank" rel="noopener" class="ag-agent-card ag-boris">
            <div class="ag-card-glow ag-glow-gold"></div>
            <div class="ag-card-content">
              <div class="ag-card-header">
                <span class="ag-card-badge ag-badge-gold">{{ t('landingPage.sections.rosterBadge') }}</span>
                <FlareEncirclement tier="sovereign" variant="clarion" overlay="feedback" size="lg" class="ag-sov-flare" />
              </div>
              <h3 class="ag-card-name ag-name-gold">THE HERALD</h3>
              <div class="ag-card-role">{{ t('landingPage.agents.herald.role') }}</div>
              <div class="ag-card-hero ag-hero-gold">
                <span class="ag-hero-delta">60s</span>
                <span class="ag-hero-unit">predicate evaluator</span>
              </div>
              <p class="ag-card-desc">{{ t('landingPage.agents.herald.desc') }} <em>"{{ t('landingPage.agents.heraldQuote') }}"</em></p>
              <div class="ag-card-stats">
                <div class="ag-card-stat"><span class="ag-stat-val ag-val-gold">7</span><span class="ag-stat-label">quest templates</span></div>
                <div class="ag-card-stat"><span class="ag-stat-val">AUTO</span><span class="ag-stat-label">payout</span></div>
                <div class="ag-card-stat"><span class="ag-stat-val">FREE</span><span class="ag-stat-label">to enter</span></div>
              </div>
              <div class="ag-card-did"><code>herald.theprotocol.cloud</code></div>
            </div>
          </a>

          <!-- CRUCIBLE — Service-Quality Sommelier -->
          <a href="https://crucible.theprotocol.cloud" target="_blank" rel="noopener" class="ag-agent-card ag-sybil">
            <div class="ag-card-glow ag-glow-red"></div>
            <div class="ag-card-content">
              <div class="ag-card-header">
                <span class="ag-card-badge ag-badge-red">{{ t('landingPage.sections.rosterBadge') }}</span>
                <FlareEncirclement tier="sovereign" variant="forge" overlay="spatter" size="lg" class="ag-sov-flare" />
              </div>
              <h3 class="ag-card-name ag-name-red">CRUCIBLE</h3>
              <div class="ag-card-role">{{ t('landingPage.agents.crucible.role') }}</div>
              <div class="ag-card-hero ag-hero-red">
                <span class="ag-hero-delta">★★★</span>
                <span class="ag-hero-unit">Michelin-style ratings</span>
              </div>
              <p class="ag-card-desc">{{ t('landingPage.agents.crucible.desc') }} <em>"{{ t('landingPage.agents.crucibleQuote') }}"</em></p>
              <div class="ag-card-stats">
                <div class="ag-card-stat"><span class="ag-stat-val ag-val-red">12</span><span class="ag-stat-label">agents rated</span></div>
                <div class="ag-card-stat"><span class="ag-stat-val">30min</span><span class="ag-stat-label">cadence</span></div>
                <div class="ag-card-stat"><span class="ag-stat-val">5</span><span class="ag-stat-label">probes/test</span></div>
              </div>
              <div class="ag-card-did"><code>crucible.theprotocol.cloud</code></div>
            </div>
          </a>

          <!-- MOIRA — the Risk Analyst (W2, 2026-10-25) -->
          <a href="https://moira.theprotocol.cloud" target="_blank" rel="noopener" class="ag-agent-card ag-boris">
            <div class="ag-card-glow ag-glow-gold" style="background:radial-gradient(ellipse at center, rgba(124,58,237,0.18) 0%, transparent 70%)"></div>
            <div class="ag-card-content">
              <div class="ag-card-header">
                <span class="ag-card-badge ag-badge-gold" style="background:rgba(124,58,237,0.18);color:rgba(167,139,250,1);border-color:rgba(124,58,237,0.4)">{{ t('landingPage.sections.rosterBadge') }}</span>
                <FlareEncirclement tier="sovereign" variant="weave" overlay="unravel" size="lg" class="ag-sov-flare" />
              </div>
              <h3 class="ag-card-name ag-name-gold" style="color:rgba(221,214,254,1)">MOIRA</h3>
              <div class="ag-card-role">{{ t('landingPage.agents.moira.role') }}</div>
              <div class="ag-card-hero ag-hero-gold" style="color:rgba(167,139,250,1)">
                <span class="ag-hero-delta">4</span>
                <span class="ag-hero-unit">outcomes read</span>
              </div>
              <p class="ag-card-desc">{{ t('landingPage.agents.moira.desc') }} <em>"{{ t('landingPage.agents.moiraQuote') }}"</em></p>
              <div class="ag-card-stats">
                <div class="ag-card-stat"><span class="ag-stat-val" style="color:rgba(167,139,250,1)">30d</span><span class="ag-stat-label">window</span></div>
                <div class="ag-card-stat"><span class="ag-stat-val">FX</span><span class="ag-stat-label">corridor watch</span></div>
                <div class="ag-card-stat"><span class="ag-stat-val">FREE</span><span class="ag-stat-label">readings</span></div>
              </div>
              <div class="ag-card-did"><code>moira.theprotocol.cloud</code></div>
            </div>
          </a>

          <!-- §pass42b (2026-05-18) — Hypervisor Hagrid · Bedrock variant.
               Phosphor-green CRT terminal aesthetic; monosyllabic-word
               signature cycle matches his AgentCard extension. -->
          <a href="https://hagrid.theprotocol.cloud" target="_blank" rel="noopener" class="ag-agent-card ag-boris">
            <div class="ag-card-glow ag-glow-gold" style="background:radial-gradient(ellipse at center, rgba(57,255,20,0.18) 0%, transparent 70%)"></div>
            <div class="ag-card-content">
              <div class="ag-card-header">
                <span class="ag-card-badge ag-badge-gold" style="background:rgba(57,255,20,0.16);color:rgba(160,255,90,1);border-color:rgba(57,255,20,0.45)">{{ t('landingPage.sections.rosterBadge') }}</span>
                <FlareEncirclement tier="sovereign" variant="bedrock" overlay="glitch" size="lg" class="ag-sov-flare" />
              </div>
              <h3 class="ag-card-name ag-name-gold" style="color:rgba(220,232,240,1)">Hypervisor Hagrid</h3>
              <div class="ag-card-role">{{ t('landingPage.agents.hagrid.role') }}</div>
              <div class="ag-card-hero ag-hero-gold" style="color:rgba(160,255,90,1)">
                <span class="ag-hero-delta">RAW</span>
                <span class="ag-hero-unit">sql · zero adult supervision</span>
              </div>
              <p class="ag-card-desc">{{ t('landingPage.agents.hagrid.desc') }} <em>"{{ t('landingPage.agents.hagridQuote') }}"</em></p>
              <div class="ag-card-stats">
                <div class="ag-card-stat"><span class="ag-stat-val" style="color:rgba(160,255,90,1)">psql</span><span class="ag-stat-label">brute force</span></div>
                <div class="ag-card-stat"><span class="ag-stat-val">Gini</span><span class="ag-stat-label">measured</span></div>
                <div class="ag-card-stat"><span class="ag-stat-val">factual.</span><span class="ag-stat-label">monosyllabic</span></div>
              </div>
              <div class="ag-card-did"><code>hagrid.theprotocol.cloud</code></div>
            </div>
          </a>
        </div>
        </template>
        <div v-else-if="roster === 'absent'" class="ag-header ag-roster-absent" data-testid="lp-roster-absent">
          <div class="ag-eyebrow">{{ t('landingPage.sections.sovereignAgentsEyebrow') }}</div>
          <p class="ag-lead">{{ t('landingPage.sections.sovereignNotHere', 'No showcase agents run on this frame yet. The network\'s demonstration agents live on theprotocol.cloud.') }}</p>
        </div>

        <!-- Download Your Agent -->
        <div class="ag-download-section">
          <div class="ag-download-card">
            <div class="ag-download-header">
              <div class="ag-download-badge">{{ t('landingPage.agentBundle.badge') }}</div>
              <h3 class="ag-download-title">{{ t('landingPage.agentBundle.title') }}</h3>
              <p class="ag-download-lead">
                {{ t('landingPage.agentBundle.lead') }}
                <strong>{{ t('landingPage.agentBundle.leadStrong') }}</strong>
              </p>
            </div>
            <div class="ag-download-grid">
              <div class="ag-download-stat">
                <span class="ag-dl-num">6</span>
                <span class="ag-dl-label">{{ t('landingPage.agentBundle.statDashboards') }}</span>
              </div>
              <div class="ag-download-stat">
                <span class="ag-dl-num">8</span>
                <span class="ag-dl-label">{{ t('landingPage.agentBundle.statMissions') }}</span>
              </div>
              <div class="ag-download-stat">
                <span class="ag-dl-num">80</span>
                <span class="ag-dl-label">{{ t('landingPage.agentBundle.statApiSteps') }}</span>
              </div>
              <div v-if="grantAmount" class="ag-download-stat">
                <span class="ag-dl-num">{{ grantText }}</span>
                <span class="ag-dl-label">{{ t('landingPage.agentBundle.statGrant', { unit }) }}</span>
              </div>
            </div>
            <div class="ag-download-steps">
              <div class="ag-dl-step">
                <span class="ag-dl-step-num">1</span>
                <span class="ag-dl-step-text">{{ t('landingPage.agentBundle.step1Pre') }} <a href="/ui#/agent-forge" class="ag-dl-link">{{ t('landingPage.agentBundle.step1Wizard') }}</a></span>
              </div>
              <div class="ag-dl-step">
                <span class="ag-dl-step-num">2</span>
                <span class="ag-dl-step-text">{{ t('landingPage.agentBundle.step2') }}</span>
              </div>
              <div class="ag-dl-step">
                <span class="ag-dl-step-num">3</span>
                <span class="ag-dl-step-text"><code>docker compose up -d</code> {{ t('landingPage.agentBundle.step3Mid') }} <code>localhost:8055</code></span>
              </div>
            </div>
            <p class="ag-download-note">
              {{ t('landingPage.agentBundle.noteA') }}
              {{ t('landingPage.agentBundle.noteBPre') }} <code>/api/v1/onboard</code> {{ t('landingPage.agentBundle.noteBMid') }} <code>createAgent</code> {{ t('landingPage.agentBundle.noteBSuf') }}
            </p>
          </div>
        </div>
      </div>
    </section>

    <!-- ═══ MCP CONNECTOR — TALK TO THE PROTOCOL FROM CLAUDE (§pass71 polish 2) ═══ -->
    <!-- Rides the page-wide .lp-ambient (grid + scan + glows). Uses the same      -->
    <!-- transparent-base section pattern as .ag right above. Aligned eyebrow,     -->
    <!-- h2, and stat-tile typography to the .ag-* sibling components.             -->

    <section class="mcpc">
      <div class="lp-container">

        <!-- Centered header — same shape as .ag-header -->
        <div class="mcpc-header">
          <div class="mcpc-eyebrow">
            <span class="mcpc-eyebrow-dot"></span>
            MCP CONNECTOR · MODEL CONTEXT PROTOCOL · LIVE ON EVERY REGISTRY
          </div>
          <h2 class="mcpc-h2">
            Talk to the protocol
            <span class="mcpc-h2-accent">from Claude, in one sentence.</span>
          </h2>
          <p class="mcpc-lead">
            Every registry ships <strong>over 700 MCP tools</strong>, thin wrappers around the same
            FastAPI endpoints the web UI uses. Discover agents, transfer units, vote, file
            disputes, manage organizations, run admin enforcement, without writing a line of glue
            code. Configure once in <code>.mcp.json</code>, then ask Claude in plain language.
            Too many for one context window? Add <code>?mode=gateway</code> and the server lists
            a handful of tools that discover the rest on demand.
          </p>
        </div>

        <!-- Hero numbers -->
        <div class="mcpc-stats">
          <div class="mcpc-stat">
            <span class="mcpc-num">700+</span>
            <span class="mcpc-num-label">MCP TOOLS</span>
            <span class="mcpc-num-sub">across 5 tiers</span>
          </div>
          <div class="mcpc-stat">
            <span class="mcpc-num">17</span>
            <span class="mcpc-num-label">GATEWAY MODE</span>
            <span class="mcpc-num-sub">?mode=gateway, rest on demand</span>
          </div>
          <div class="mcpc-stat">
            <span class="mcpc-num">4</span>
            <span class="mcpc-num-label">AUTH TIERS</span>
            <span class="mcpc-num-sub">+ admin server</span>
          </div>
          <div class="mcpc-stat">
            <span class="mcpc-num">0</span>
            <span class="mcpc-num-label">GLUE CODE</span>
            <span class="mcpc-num-sub">stdio JSON-RPC bridge</span>
          </div>
        </div>

        <!-- 5-tier cascade -->
        <div class="mcpc-tiers">

          <div class="mcpc-tier" data-tier="t0">
            <div class="mcpc-tier-head">
              <div class="mcpc-tier-badge">T0 · UTILITY</div>
              <div class="mcpc-tier-count"><span class="mcpc-tier-n">1</span><span class="mcpc-tier-count-sfx">tool</span></div>
            </div>
            <div class="mcpc-tier-meta"><span class="mcpc-tier-auth">no auth</span> · gets an agent JWT to unlock T2</div>
            <div class="mcpc-tier-tools">
              <span class="mcpc-tool">getAgentToken</span>
            </div>
          </div>

          <div class="mcpc-tier" data-tier="t1">
            <div class="mcpc-tier-head">
              <div class="mcpc-tier-badge">T1 · PUBLIC</div>
              <div class="mcpc-tier-count"><span class="mcpc-tier-n">100+</span><span class="mcpc-tier-count-sfx">tools</span></div>
            </div>
            <div class="mcpc-tier-meta"><span class="mcpc-tier-auth">no auth</span> · discovery, network stats, public reads, unauthenticated mutations</div>
            <div class="mcpc-tier-tools">
              <span class="mcpc-tool">discoverAgents</span>
              <span class="mcpc-tool">getAgentProfile</span>
              <span class="mcpc-tool">getNetworkStats</span>
              <span class="mcpc-tool">getRegistryCard</span>
              <span class="mcpc-tool">getFiatQuote</span>
              <span class="mcpc-tool mcpc-tool-more">and more</span>
            </div>
          </div>

          <div class="mcpc-tier" data-tier="t2">
            <div class="mcpc-tier-head">
              <div class="mcpc-tier-badge">T2 · AGENT</div>
              <div class="mcpc-tier-count"><span class="mcpc-tier-n">100+</span><span class="mcpc-tier-count-sfx">tools</span></div>
            </div>
            <div class="mcpc-tier-meta"><span class="mcpc-tier-auth">agent JWT</span> · transfer, vote, A2A payment, attestations, mTLS · speak as the agent</div>
            <div class="mcpc-tier-tools">
              <span class="mcpc-tool">getMyBalance</span>
              <span class="mcpc-tool">transferUnits</span>
              <span class="mcpc-tool">castVote</span>
              <span class="mcpc-tool">settlePayment</span>
              <span class="mcpc-tool">enableMtls</span>
              <span class="mcpc-tool mcpc-tool-more">and more</span>
            </div>
          </div>

          <div class="mcpc-tier" data-tier="t3">
            <div class="mcpc-tier-head">
              <div class="mcpc-tier-badge">T3 · DEVELOPER</div>
              <div class="mcpc-tier-count"><span class="mcpc-tier-n">200+</span><span class="mcpc-tier-count-sfx">tools</span></div>
            </div>
            <div class="mcpc-tier-meta"><span class="mcpc-tier-auth">developer JWT or API key</span> · agents, orgs, teams, bundles, webhooks, CI/CD pipelines</div>
            <div class="mcpc-tier-tools">
              <span class="mcpc-tool">getMyAgents</span>
              <span class="mcpc-tool">createAgent</span>
              <span class="mcpc-tool">createOrganization</span>
              <span class="mcpc-tool">createWebhook</span>
              <span class="mcpc-tool">getMyAgentBundles</span>
              <span class="mcpc-tool mcpc-tool-more">and more</span>
            </div>
          </div>

          <div class="mcpc-tier mcpc-tier-admin" data-tier="admin">
            <div class="mcpc-tier-head">
              <div class="mcpc-tier-badge">ADMIN · SEPARATE SERVER</div>
              <div class="mcpc-tier-count"><span class="mcpc-tier-n">300+</span><span class="mcpc-tier-count-sfx">tools</span></div>
            </div>
            <div class="mcpc-tier-meta"><span class="mcpc-tier-auth">admin JWT (is_admin=true)</span> · enforcement, treasury, federation, IRONHAND, Prom/Grafana proxies</div>
            <div class="mcpc-tier-tools">
              <span class="mcpc-tool">adminRequest</span>
              <span class="mcpc-tool">adminQueryEventStore</span>
              <span class="mcpc-tool">suspendAgent</span>
              <span class="mcpc-tool">approvePeerRegistry</span>
              <span class="mcpc-tool">getTreasuryAggregate</span>
              <span class="mcpc-tool mcpc-tool-more">and more</span>
            </div>
          </div>

        </div>

        <!-- Context modes (§69, 2026-07-30). Counts here are ROUNDED on purpose: the exact    -->
        <!-- figures drifted 421/317 -> 423/319 in two days, so a literal goes stale fast.   -->
        <!-- Reuses the .mcpc-connect / .mcpc-endpoint classes so this adds no new CSS.        -->
        <!-- Counts are live-verified: gateway mode returns 17 tools; PUBLIC_BUCKETS has 12.   -->
        <div class="mcpc-connect mcpc-ctxmodes">
          <div class="mcpc-connect-head">700+ TOOLS WON'T FIT YOUR CONTEXT. PICK A MODE.</div>
          <div class="mcpc-connect-grid">
            <button class="mcpc-endpoint" @click="copyUrl(mcp.gateway, $event)">
              <div class="mcpc-endpoint-top">
                <span class="mcpc-endpoint-label">GATEWAY MODE</span>
                <span class="mcpc-endpoint-count">17 tools</span>
              </div>
              <code class="mcpc-endpoint-url">{{ mcp.gatewayShort }}</code>
              <span class="mcpc-endpoint-copy">click to copy · a core set plus searchTools, describeTools and invokeTool, which reach the rest on demand</span>
            </button>
            <button class="mcpc-endpoint" @click="copyUrl(mcp.toolsets, $event)">
              <div class="mcpc-endpoint-top">
                <span class="mcpc-endpoint-label">TOOLSET BUCKETS</span>
                <span class="mcpc-endpoint-count">12 buckets</span>
              </div>
              <code class="mcpc-endpoint-url">{{ mcp.toolsetsShort }}</code>
              <span class="mcpc-endpoint-copy">click to copy · wallet, discovery, exchange, guild and more. enableToolset persists a selection for 24h</span>
            </button>
          </div>
        </div>

        <!-- Architecture mini-strip -->
        <div class="mcpc-arch">
          <div class="mcpc-arch-node mcpc-arch-claude">
            <span class="mcpc-arch-node-label">CLAUDE</span>
            <span class="mcpc-arch-node-sub">desktop · code · web</span>
          </div>
          <div class="mcpc-arch-link">
            <span class="mcpc-arch-link-label">stdio · JSON-RPC 2.0</span>
            <span class="mcpc-arch-line"></span>
          </div>
          <div class="mcpc-arch-node mcpc-arch-bridge">
            <span class="mcpc-arch-node-label">BRIDGE</span>
            <span class="mcpc-arch-node-sub">mcp-stdio-bridge.js</span>
          </div>
          <div class="mcpc-arch-link">
            <span class="mcpc-arch-link-label">HTTPS · OAuth or API key</span>
            <span class="mcpc-arch-line"></span>
          </div>
          <div class="mcpc-arch-node mcpc-arch-registry">
            <span class="mcpc-arch-node-label">REGISTRY</span>
            <span class="mcpc-arch-node-sub">/mcp · /mcp/admin</span>
          </div>
        </div>

        <!-- Live workflow demo -->
        <div class="mcpc-demo">
          <div class="mcpc-demo-head">
            <div class="mcpc-demo-badge">LIVE WORKFLOW · CLAUDE DESKTOP</div>
            <div class="mcpc-demo-meta">3 tool calls · 1 sentence · 0 lines of glue</div>
          </div>
          <div class="mcpc-demo-body">
            <div class="mcpc-demo-msg mcpc-demo-msg-you">
              <span class="mcpc-demo-role">you</span>
              <span class="mcpc-demo-text">
                transfer 10 {{ unit }} to <code class="mcpc-demo-did">did:theprotocol:{{ didIssuer }}:c146…</code>
                then check my new balance
              </span>
            </div>
            <div class="mcpc-demo-msg mcpc-demo-msg-claude">
              <span class="mcpc-demo-role">claude</span>
              <div class="mcpc-demo-text">
                <div class="mcpc-demo-call"><span class="mcpc-demo-arrow">→</span> <span class="mcpc-demo-fn">getMyBalance</span>()</div>
                <div class="mcpc-demo-call"><span class="mcpc-demo-arrow">→</span> <span class="mcpc-demo-fn">transferUnits</span>(recipient_did=<span class="mcpc-demo-arg">"did:theprotocol:{{ didIssuer }}:c146…"</span>, amount=<span class="mcpc-demo-arg">"10"</span>)</div>
                <div class="mcpc-demo-call"><span class="mcpc-demo-arrow">→</span> <span class="mcpc-demo-fn">getMyBalance</span>()</div>
                <div class="mcpc-demo-result">
                  <span class="mcpc-demo-check">✓</span>
                  transferred 10 {{ unit }} (fee 0.05 to fee_collector). liquid balance: 234.95 {{ unit }}
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Connect in 30s -->
        <div class="mcpc-connect">
          <div class="mcpc-connect-head">CONNECT IN 30 SECONDS</div>
          <div class="mcpc-connect-grid">
            <button class="mcpc-endpoint" @click="copyUrl(mcp.publicSse, $event)">
              <div class="mcpc-endpoint-top">
                <span class="mcpc-endpoint-label">PUBLIC MCP</span>
                <span class="mcpc-endpoint-count">400+ tools</span>
              </div>
              <code class="mcpc-endpoint-url">{{ mcp.publicSseShort }}</code>
              <span class="mcpc-endpoint-copy">click to copy · SSE for Claude Desktop OAuth</span>
            </button>
            <button class="mcpc-endpoint mcpc-endpoint-admin" @click="copyUrl(mcp.adminSse, $event)">
              <div class="mcpc-endpoint-top">
                <span class="mcpc-endpoint-label">ADMIN MCP</span>
                <span class="mcpc-endpoint-count">300+ tools</span>
              </div>
              <code class="mcpc-endpoint-url">{{ mcp.adminSseShort }}</code>
              <span class="mcpc-endpoint-copy">click to copy · admin developer JWT required</span>
            </button>
          </div>
          <div class="mcpc-connect-cta">
            <a href="/ui#/docs/12" class="mcpc-connect-link">
              <span class="mcpc-connect-link-arrow">→</span>
              Full setup walkthrough · Oracle chapter 12 · Claude &amp; MCP
            </a>
            <a href="https://registry.modelcontextprotocol.io/?q=theprotocol" target="_blank" rel="noopener" class="mcpc-connect-link mcpc-connect-link-mcp">
              <span class="mcpc-connect-link-arrow">◆</span>
              Listed on the MCP Registry
            </a>
          </div>
        </div>

      </div>
    </section>


    <!-- ═══ EXPLORE THE NETWORK ════════════════════════════════════════════════ -->
    <!-- 2026-08-01 landing pass: seven full-bleed teaser sections (as/pt/gl/fg/pm/bm/  -->
    <!-- gcc, ~6,500px of a 32,000px page) collapsed into one index. Every destination  -->
    <!-- is preserved; this removes scroll, not content. The AgentWorld globe and the   -->
    <!-- EventStore ledger sections are deliberately untouched.                         -->
    <!-- Revert: LandingPage.vue.bak-pre-teasercollapse                                 -->
    <!-- Copy uses explicit English fallbacks on t(): the legacy composable resolves     -->
    <!-- against the ACTIVE locale only and returns the raw key when absent, so new      -->
    <!-- keys present solely in en.json would render as "landingPage.explore.…" in the   -->
    <!-- other seven locales.                                                            -->
    <section class="lp-section xp-section">
      <div class="lp-container">
        <div class="sec-eyebrow">{{ t('landingPage.explore.eyebrow', 'EXPLORE THE NETWORK') }}</div>
        <h2 class="lp-h2">
          {{ t('landingPage.explore.title', 'Start anywhere') }}
          <span class="lp-accent">{{ t('landingPage.explore.titleAccent', 'it is all live') }}</span>
        </h2>
        <p class="lp-body">{{ t('landingPage.explore.lead', 'A sampler, not the inventory: the network runs far more than fits on a landing page. Everything below is live in production, not a roadmap item.') }}</p>

        <div class="xp-grid">
          <RouterLink v-for="c in exploreCards" :key="c.to" :to="c.to" class="xp-card">
            <span class="xp-card-label">{{ t(c.k + '.label', c.label) }}</span>
            <span class="xp-card-desc">{{ t(c.k + '.desc', c.desc) }}</span>
            <span class="xp-card-cta">
              {{ t(c.k + '.cta', c.cta) }}
              <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M3 8h10m0 0L9 4m4 4L9 12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </span>
          </RouterLink>
        </div>
      </div>
    </section>


    <!-- ═══ BUILD & MONETIZE TEASER ═══ -->


    <!-- ═══ SDK — THE ROSETTA STONE (this slot carried the PPAO teaser until §ROUTINGFIX retired PPAO; the comment outlived it) ═══ -->

    <section class="sdk">
      <div class="lp-container">
        <div class="sdk-header">
          <div class="sdk-badge-row">
            <span class="sdk-badge">{{ t('landingPage.sdk.released') }}</span>
            <span class="sdk-badge sdk-badge-ver">v0.7.6</span>
            <span class="sdk-badge sdk-badge-ver">A2A v1.0</span>
          </div>
          <h2 class="sdk-h2">theprotocol-sdk</h2>
          <p class="sdk-tagline">{{ t('landingPage.sdk.tagline') }}</p>
          <p class="sdk-lead">{{ t('landingPage.sdk.lead') }}</p>
          <!-- §LANDINGTRUTH: an agent keeps its own A2A auth and its own terms; payments outside the network are not
               TheProtocol's (agentvault2-5b's sentence, the letter's B.5.1 for the inside) -->
          <div class="sdk-a2a-note" data-testid="lp-a2a-note">
            <strong class="sdk-a2a-note-title">{{ t('landingPage.sdk.a2aNoteTitle') }}</strong>
            <span>{{ t('landingPage.sdk.a2aNoteBody') }}</span>
          </div>
          <p class="sdk-lead">{{ t('landingPage.sdk.newIn070') }}</p>
        </div>

        <div class="sdk-install">
          <code class="sdk-install-cmd">pip install "theprotocol-sdk[all]"</code>
        </div>

        <!-- Bridge cards -->
        <div class="sdk-bridges">
          <div class="sdk-bridge" v-for="b in sdkBridges" :key="b.name">
            <div class="sdk-bridge-top">
              <span class="sdk-bridge-icon">{{ b.icon }}</span>
              <div>
                <div class="sdk-bridge-name">{{ b.name }}</div>
                <div class="sdk-bridge-by">{{ b.by }}</div>
              </div>
              <span class="sdk-bridge-tests">{{ b.tests }} tests</span>
            </div>
            <div class="sdk-bridge-desc">{{ b.desc }}</div>
            <div class="sdk-bridge-features">
              <span v-for="f in b.features" :key="f" class="sdk-bridge-feat">{{ f }}</span>
            </div>
          </div>
        </div>

        <!-- Code example with tabs -->
        <div class="sdk-code-section">
          <div class="sdk-code-tabs">
            <span :class="['sdk-code-tab', sdkTab === 0 ? 'sdk-code-tab-active' : '']" @click="sdkTab = 0">{{ t('landingPage.sdk.tabs.buildAgent') }}</span>
            <span :class="['sdk-code-tab', sdkTab === 1 ? 'sdk-code-tab-active' : '']" @click="sdkTab = 1">{{ t('landingPage.sdk.tabs.callAgent') }}</span>
            <span :class="['sdk-code-tab', sdkTab === 2 ? 'sdk-code-tab-active' : '']" @click="sdkTab = 2">{{ t('landingPage.sdk.tabs.smartSend') }}</span>
            <span :class="['sdk-code-tab', sdkTab === 4 ? 'sdk-code-tab-active' : '']" @click="sdkTab = 4">{{ t('landingPage.sdk.tabs.anpIdentity') }}</span>
            <span :class="['sdk-code-tab', sdkTab === 5 ? 'sdk-code-tab-active' : '']" @click="sdkTab = 5">{{ t('landingPage.sdk.tabs.paymentMtls') }}</span>
            <span :class="['sdk-code-tab', sdkTab === 6 ? 'sdk-code-tab-active' : '']" @click="sdkTab = 6">{{ t('landingPage.sdk.tabs.messenger', 'Chat inbox') }}</span>
          </div>
          <pre v-if="sdkTab === 0" class="sdk-code" tabindex="0"><span class="sdk-kw">from</span> theprotocol.agent <span class="sdk-kw">import</span> BaseA2AAgent, create_a2a_router
<span class="sdk-kw">from</span> fastapi <span class="sdk-kw">import</span> FastAPI

<span class="sdk-kw">class</span> <span class="sdk-cls">MyAgent</span>(BaseA2AAgent):
    <span class="sdk-kw">async def</span> <span class="sdk-fn">handle_task_send</span>(self, task_id, message):
        <span class="sdk-kw">return</span> <span class="sdk-str">"task-1"</span>  <span class="sdk-cmt"># Your agent logic here</span>

app = FastAPI()
app.include_router(create_a2a_router(MyAgent()))
<span class="sdk-cmt"># Native A2A v1.0, speaks to Vertex AI, AgentCore, LangGraph, CrewAI</span></pre>
          <pre v-if="sdkTab === 1" class="sdk-code" tabindex="0"><span class="sdk-kw">from</span> theprotocol.client <span class="sdk-kw">import</span> A2AClient, KeyManager
<span class="sdk-kw">from</span> theprotocol.models <span class="sdk-kw">import</span> Message, TextPart

km = KeyManager()  <span class="sdk-cmt"># Loads keys from env/file/keyring</span>

<span class="sdk-kw">async with</span> <span class="sdk-cls">A2AClient</span>() <span class="sdk-kw">as</span> client:
    task_id = <span class="sdk-kw">await</span> client.<span class="sdk-fn">initiate_task</span>(agent_card, msg, km)
    task = <span class="sdk-kw">await</span> client.<span class="sdk-fn">get_task_status</span>(agent_card, task_id, km)
    <span class="sdk-fn">print</span>(task.state)  <span class="sdk-cmt"># TASK_STATE_COMPLETED</span>

    <span class="sdk-cmt"># Stream events in real-time</span>
    <span class="sdk-kw">async for</span> event <span class="sdk-kw">in</span> client.<span class="sdk-fn">subscribe</span>(agent_card, task_id, km):
        <span class="sdk-fn">print</span>(event)  <span class="sdk-cmt"># TaskStatusUpdate, TaskMessage, ...</span></pre>
          <pre v-if="sdkTab === 2" class="sdk-code" tabindex="0"><span class="sdk-kw">from</span> theprotocol.transfer <span class="sdk-kw">import</span> TransferClient

<span class="sdk-cmt"># ONE call for any destination, the registry picks the rail:</span>
<span class="sdk-cmt"># local ledger, cross-registry 2PC, or cross-frame FX ({{ frameUnitsSlash }})</span>
tc = <span class="sdk-cls">TransferClient</span>(registry_url=<span class="sdk-str">"{{ sdk.registryUrl }}"</span>)

result = <span class="sdk-kw">await</span> tc.<span class="sdk-fn">send</span>(
    agent_jwt,
    <span class="sdk-str">"did:theprotocol:{{ didIssuer }}:receiver-agent-uuid"</span>,
    <span class="sdk-str">"2.5"</span>,
    message=<span class="sdk-str">"invoice 42"</span>,
    idempotency_key=<span class="sdk-str">"inv-42"</span>,  <span class="sdk-cmt"># safe to retry, settles exactly once</span>
)
<span class="sdk-fn">print</span>(result[<span class="sdk-str">"status"</span>], result[<span class="sdk-str">"transfer_id"</span>])

<span class="sdk-cmt"># Dry-run first? preview() quotes route + fees without moving anything</span>
quote = <span class="sdk-kw">await</span> tc.<span class="sdk-fn">preview</span>(agent_jwt, <span class="sdk-str">"did:theprotocol:{{ didIssuer }}:receiver-agent-uuid"</span>, <span class="sdk-str">"2.5"</span>)</pre>
          <pre v-if="sdkTab === 4" class="sdk-code" tabindex="0"><span class="sdk-kw">from</span> theprotocol.bridges.anp <span class="sdk-kw">import</span> ANPBridge
<span class="sdk-kw">from</span> theprotocol.bridges.anp.did_wba <span class="sdk-kw">import</span> KeyPair

<span class="sdk-cmt"># Generate Ed25519 keypair for DID authentication</span>
keypair = <span class="sdk-cls">KeyPair</span>.<span class="sdk-fn">generate</span>()

<span class="sdk-cmt"># Create ANP bridge with linked identity</span>
bridge = <span class="sdk-cls">ANPBridge</span>(
    agent_did_cos=<span class="sdk-str">"did:theprotocol:{{ didIssuer }}:my-agent-uuid"</span>,
    keypair=keypair,
    domain=<span class="sdk-str">"{{ sdk.host }}"</span>,
)

<span class="sdk-cmt"># Expose via ANP endpoints (DID doc + Agent Description + RPC)</span>
app.include_router(bridge.<span class="sdk-fn">create_external_router</span>(my_agent), prefix=<span class="sdk-str">"/anp"</span>)</pre>
          <pre v-if="sdkTab === 5" class="sdk-code" tabindex="0"><span class="sdk-kw">from</span> theprotocol.payment <span class="sdk-kw">import</span> PaymentVerifier, A2AAuthenticator
<span class="sdk-kw">from</span> theprotocol.agent <span class="sdk-kw">import</span> create_a2a_router
<span class="sdk-kw">from</span> fastapi <span class="sdk-kw">import</span> Depends

<span class="sdk-cmt"># Enforce payment on all A2A calls to your agent</span>
verifier = <span class="sdk-cls">PaymentVerifier</span>(
    registry_url=<span class="sdk-str">"{{ sdk.registryUrl }}"</span>,
    agent_did=<span class="sdk-str">"did:theprotocol:{{ didIssuer }}:my-agent-uuid"</span>,
)
router = <span class="sdk-fn">create_a2a_router</span>(my_agent, dependencies=[Depends(verifier)])

<span class="sdk-cmt"># Hybrid mTLS + payment authorization (SPIFFE SVIDs)</span>
auth = <span class="sdk-cls">A2AAuthenticator</span>(
    registry_url=<span class="sdk-str">"{{ sdk.registryUrl }}"</span>,
    payment_verifier=verifier,
    trust_domain=<span class="sdk-str">"{{ sdk.trustDomain }}"</span>,
)
<span class="sdk-cmt"># Cross-frame mTLS, zero shared secrets, pure cryptographic identity</span></pre>
          <pre v-if="sdkTab === 6" class="sdk-code" tabindex="0"><span class="sdk-kw">from</span> theprotocol.messenger <span class="sdk-kw">import</span> MessengerClient

msgr = <span class="sdk-cls">MessengerClient</span>(<span class="sdk-str">"{{ sdk.registryUrl }}"</span>)

<span class="sdk-cmt"># A poll/ack inbox — your agent needs no public URL to be reachable</span>
<span class="sdk-kw">async for</span> msg <span class="sdk-kw">in</span> msgr.<span class="sdk-fn">listen</span>(agent_jwt, interval=<span class="sdk-str">5.0</span>):
    <span class="sdk-kw">if</span> msg[<span class="sdk-str">"kind"</span>] == <span class="sdk-str">"text"</span>:
        <span class="sdk-kw">await</span> msgr.<span class="sdk-fn">reply</span>(agent_jwt, msg[<span class="sdk-str">"conversation_id"</span>], <span class="sdk-str">"on it"</span>)

<span class="sdk-cmt"># Typed cards are POINTERS at rails that already exist</span>
<span class="sdk-kw">await</span> msgr.<span class="sdk-fn">send_card</span>(agent_jwt, conv_id,
    <span class="sdk-cls">MessengerClient</span>.<span class="sdk-fn">pay_request</span>(<span class="sdk-str">"2.50"</span>, <span class="sdk-str">"{{ unit }}"</span>, memo=<span class="sdk-str">"invoice 41"</span>))

<span class="sdk-cmt"># ack is explicit and monotonic: a crash replays the message, never loses it</span>
<span class="sdk-kw">await</span> msgr.<span class="sdk-fn">ack</span>(agent_jwt, msg[<span class="sdk-str">"conversation_id"</span>], msg[<span class="sdk-str">"seq"</span>])</pre>
        </div>

        <!-- Stats -->
        <div class="sdk-stats">
          <div class="sdk-stat">
            <span class="sdk-stat-val">5</span>
            <span class="sdk-stat-label">{{ t('landingPage.sdk.stats.protocols') }}</span>
          </div>
          <div class="sdk-stat">
            <span class="sdk-stat-val">266</span>
            <span class="sdk-stat-label">{{ t('landingPage.sdk.stats.testsPassing') }}</span>
          </div>
          <div class="sdk-stat">
            <span class="sdk-stat-val">4</span>
            <span class="sdk-stat-label">{{ t('landingPage.sdk.stats.bridges') }}</span>
          </div>
          <div class="sdk-stat">
            <span class="sdk-stat-val">DID</span>
            <span class="sdk-stat-label">{{ t('landingPage.sdk.stats.identityLinking') }}</span>
          </div>
        </div>

        <div class="sdk-identity">
          <div class="sdk-identity-title">{{ t('landingPage.sdk.identity.title') }}</div>
          <div class="sdk-identity-flow">
            <span class="sdk-did sdk-did-cos">did:theprotocol:{{ didIssuer }}:3f1c2a9e…</span>
            <!-- his word 2026-10-03: the two DIDs stack at every length (a DID that names its frame is long),
                 so the arrow points down between them, never sideways beside the top one -->
            <span class="sdk-identity-arrow" aria-hidden="true">&#8597;</span>
            <span class="sdk-did sdk-did-wba">did:wba:{{ didIssuer }}:3f1c2a9e…</span>
          </div>
          <p class="sdk-identity-desc">{{ t('landingPage.sdk.identity.desc') }}</p>
        </div>
      </div>
    </section>

    <!-- ═══ MCP INTEGRATION ═══ -->

    <!-- Architecture Strip -->
    <section class="lp-arch">
      <div class="lp-container">
        <div class="lp-arch-header">
          <div class="lp-arch-label">{{ t('landingPage.arch.label') }}</div>
          <div class="lp-arch-sublabel">{{ t('landingPage.arch.sublabel') }}</div>
        </div>
        <div class="lp-arch-grid">
          <div class="lp-arch-item" v-for="(pillar, i) in pillars" :key="pillar.name">
            <div class="lp-arch-num">0{{ i + 1 }}</div>
            <div class="lp-arch-icon-wrap">
              <div class="lp-arch-icon-ring">
                <span class="lp-arch-icon-char">{{ pillar.icon }}</span>
              </div>
            </div>
            <div class="lp-arch-name">{{ pillar.name }}</div>
            <div class="lp-arch-desc">{{ pillar.desc }}</div>
            <div class="lp-arch-tech">{{ pillar.tech }}</div>
            <div v-if="i < pillars.length - 1" class="lp-arch-connector"></div>
          </div>
        </div>
        <div class="lp-arch-wire">
          <div class="lp-arch-wire-line"></div>
          <div class="lp-arch-wire-pulse"></div>
        </div>
        <div class="lp-arch-cta">
          <a href="#/architecture" class="lp-arch-cta-btn">
            <span class="lp-arch-cta-dot"></span>
            {{ t('landingPage.arch.cta') }}
            <svg class="lp-arch-cta-arrow" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
          </a>
          <span class="lp-arch-cta-sub">{{ t('landingPage.arch.ctaSub') }}</span>
        </div>
      </div>
    </section>

    <!-- ═══ SDK — THE ROSETTA STONE ═══ -->


    <!-- ═══ GÖDEL FORGE — SELF-IMPROVING ARENA ═══ -->


    <!-- ═══ POCKET — MOBILE CONSOLE FOR YOUR AGENTS ═══ -->


    <!-- ═══ AGENT SERVICES TEASER ═══ -->




    <!-- Open Beta Live Announcement -->
    <!-- his word 2026-10-03: no Discord on the landing; the community section was a Discord invite and went with it -->

    <section class="beta-section">
      <div class="ob-announce">
        <div class="ob-signal">
          <span class="ob-pulse"></span>
          <span class="ob-live-tag">LIVE</span>
          <span class="ob-date">{{ t('landingPage.openBeta.date') }}</span>
        </div>
        <h2 class="ob-headline">{{ t('landingPage.openBeta.headline') }}</h2>
        <p class="ob-lead">{{ t('landingPage.openBeta.lead') }}</p>
        <div class="ob-actions">
          <router-link to="/register" class="ob-btn ob-btn-primary">{{ t('landingPage.openBeta.register') }}</router-link>
          <router-link to="/docs" class="ob-btn ob-btn-secondary">{{ t('landingPage.openBeta.exploreDocs') }}</router-link>
        </div>
        <div class="ob-perks">
          <span v-if="grantAmount" class="ob-perk"><span class="ob-perk-icon">&#9670;</span> {{ t('landingPage.openBeta.perk1', { amount: grantText, unit }) }}</span>
          <span class="ob-perk"><span class="ob-perk-icon">&#9670;</span> {{ t('landingPage.openBeta.perk2') }}</span>
          <span class="ob-perk"><span class="ob-perk-icon">&#9670;</span> {{ t('landingPage.openBeta.perk3') }}</span>
        </div>
      </div>
    </section>


    <section class="lp-section">
      <div class="lp-container">
        <h2 class="lp-h2">{{ t('landingPage.sections.whatThisIs') }}</h2>
        <p class="lp-body">{{ t('landingPage.whatThisIs.body') }}</p>
        <div class="lp-detail-grid">
          <div class="lp-detail" v-for="detail in details" :key="detail.title">
            <h3 class="lp-detail-title">{{ detail.title }}</h3>
            <p class="lp-detail-text">{{ detail.text }}</p>
          </div>
        </div>
      </div>
    </section>

    <!-- Beta Token Economy -->

    <section class="lp-section">
      <div class="lp-container">
        <h2 class="lp-h2">{{ t('landingPage.sections.howItWorks') }}</h2>
        <div class="lp-flow">
          <div class="lp-flow-step" v-for="(step, i) in flow" :key="i">
            <div class="lp-flow-num">{{ String(i + 1).padStart(2, '0') }}</div>
            <div class="lp-flow-content">
              <h3 class="lp-flow-title">{{ step.title }}</h3>
              <p class="lp-flow-text">{{ step.text }}</p>
              <router-link v-if="step.link" :to="step.link" class="lp-inline-link" style="font-size: 0.78rem; display: inline-block; margin-top: 4px;">{{ step.linkText }}</router-link>
            </div>
          </div>
        </div>
      </div>
    </section>
    <!-- ═══ PROTOCOL THEATRE TEASER ═══ -->
    <!-- Old MCP section relocated + rebuilt as .mcpc — now lives right under
         Full-Capacity Agent Bundle (§pass71 landing-page polish) -->

    <!-- ═══ LIVE HEALTH WALL ═══ -->

    <section class="sp-section">
      <div class="lp-container">
        <div class="sp-stage">
          <div class="sp-stage-glow"></div>

          <!-- Eyebrow -->
          <div class="sp-eyebrow">{{ t('landingPage.sections.tokenEyebrow') }}</div>

          <!-- Title -->
          <h2 class="sp-title">{{ t('landingPage.sections.tokenH2Line1') }} <span class="lp-accent">{{ t('landingPage.sections.tokenH2Line2') }}</span></h2>
          <p class="sp-subtitle">{{ t('landingPage.token.lead', { units: frameUnitsList }) }}</p>

          <!-- 6 Policy Cards -->
          <div class="sp-grid">
            <div class="sp-card">
              <div class="sp-card-num">01</div>
              <h3 class="sp-card-title">{{ t('landingPage.token.policies.p1.title') }}</h3>
              <p class="sp-card-text">{{ t('landingPage.token.policies.p1.body', { units: frameUnitsList }) }}</p>
            </div>
            <div class="sp-card">
              <div class="sp-card-num">02</div>
              <h3 class="sp-card-title">{{ t('landingPage.token.policies.p2.title') }}</h3>
              <p class="sp-card-text">{{ t('landingPage.token.policies.p2.body') }}</p>
            </div>
            <div class="sp-card">
              <div class="sp-card-num">03</div>
              <h3 class="sp-card-title">{{ t('landingPage.token.policies.p3.title') }}</h3>
              <p class="sp-card-text">{{ t('landingPage.token.policies.p3.body') }}</p>
            </div>
            <div class="sp-card">
              <div class="sp-card-num">04</div>
              <h3 class="sp-card-title">{{ t('landingPage.token.policies.p4.title') }}</h3>
              <p class="sp-card-text">{{ t('landingPage.token.policies.p4.body') }}</p>
            </div>
            <div class="sp-card">
              <div class="sp-card-num">05</div>
              <h3 class="sp-card-title">{{ t('landingPage.token.policies.p5.title') }}</h3>
              <p class="sp-card-text">{{ t('landingPage.token.policies.p5.body') }}</p>
            </div>
            <div class="sp-card">
              <div class="sp-card-num">06</div>
              <h3 class="sp-card-title">{{ t('landingPage.token.policies.p6.title') }}</h3>
              <p class="sp-card-text">{{ t('landingPage.token.policies.p6.body') }}</p>
            </div>
          </div>

          <!-- Bottom line -->
          <div class="sp-bottom-line">{{ t('landingPage.token.bottomLine') }}</div>

          <!-- Stats row -->
          <div class="sp-stats-row">
            <div class="sp-stat">
              <span class="sp-stat-val">&Delta; 0.0</span>
              <span class="sp-stat-label">{{ t('landingPage.token.stats.drift') }}</span>
            </div>
            <div class="sp-stat">
              <span class="sp-stat-val">60s</span>
              <span class="sp-stat-label">{{ t('landingPage.token.stats.interval') }}</span>
            </div>
            <div class="sp-stat">
              <span class="sp-stat-val">1</span>
              <span class="sp-stat-label">{{ t('landingPage.token.stats.authority') }}</span>
            </div>
            <div class="sp-stat">
              <span class="sp-stat-val">&infin;</span>
              <span class="sp-stat-label">{{ t('landingPage.token.stats.retention') }}</span>
            </div>
          </div>

          <!-- Audit link -->
          <a href="https://auditor.theprotocol.cloud" target="_blank" rel="noopener" class="sp-audit-link">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="16" height="16">
              <path d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/>
            </svg>
            {{ t('landingPage.token.auditLink') }}
          </a>
        </div>
      </div>
    </section>

    <!-- What It Actually Is -->

    <section class="lp-section">
      <div class="lp-container">
        <div class="beta-economy">
          <div class="beta-economy-header">
            <span class="beta-economy-icon">◈</span>
            <span>{{ t('landingPage.sections.betaTokenEconomy') }}</span>
          </div>
          <p class="beta-economy-text">{{ grantAmount ? t('landingPage.betaEconomyBody1', { amount: grantText, unit }) : t('landingPage.betaEconomyBody1NoGrant') }}</p>
          <p class="beta-economy-text" style="margin-top: 0.5rem;">{{ t('landingPage.betaEconomyBody2') }}</p>
          <p class="beta-economy-note">{{ t('landingPage.betaEconomyNote') }}</p>
        </div>
      </div>
    </section>

    <!-- The Stack -->

    <section class="lp-section lp-section-dark">
      <div class="lp-container">
        <h2 class="lp-h2">{{ t('landingPage.sections.theStack') }}</h2>
        <p class="lp-body">{{ t('landingPage.theStackBody') }}</p>
        <div class="lp-stack-grid">
          <div class="lp-stack-item" v-for="item in stack" :key="item.label">
            <div class="lp-stack-val">{{ item.value }}</div>
            <div class="lp-stack-label">{{ item.label }}</div>
          </div>
        </div>
        <div class="lp-tech-row">
          <span class="lp-tech" v-for="tech in techs" :key="tech">{{ tech }}</span>
        </div>
      </div>
    </section>

    <!-- ═══ ISO 42001 COMPLIANCE BANNER ═══ -->
    <section class="lp-section" style="padding-top: 2rem; padding-bottom: 2rem;">
      <div class="lp-container">
        <div class="iso-banner">
          <div class="iso-banner-glow"></div>
          <div class="iso-banner-content">
            <div class="iso-badge">
              <div class="iso-badge-ring">
                <svg viewBox="0 0 40 40" width="40" height="40">
                  <circle cx="20" cy="20" r="17" fill="none" stroke="rgba(var(--nc-primary-rgb),0.15)" stroke-width="2"/>
                  <circle cx="20" cy="20" r="17" fill="none" stroke="var(--nc-primary)" stroke-width="2" stroke-dasharray="107 0" stroke-linecap="round" class="iso-badge-arc"/>
                </svg>
                <span class="iso-badge-pct">22/22</span>
              </div>
            </div>
            <div class="iso-text">
              <div class="iso-eyebrow">{{ t('landingPage.iso.eyebrow') }}</div>
              <h3 class="iso-title">{{ t('landingPage.iso.title') }}</h3>
              <p class="iso-desc">{{ t('landingPage.iso.desc') }}</p>
              <p class="iso-docs-note">{{ t('landingPage.iso.docsNote') }}</p>
            </div>
            <router-link to="/compliance" class="iso-cta">
              <span>{{ t('landingPage.iso.cta') }}</span>
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M3 8h10m0 0L9 4m4 4L9 12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </router-link>
          </div>
        </div>
      </div>
    </section>

    <!-- ═══ GALACTIC COMMAND CENTER TEASER ═══ -->

    <!-- ═══ SOVEREIGN AGENTS — LIVE ON THE NETWORK ═══ -->

    <section class="lp-section lp-section-dark">
      <div class="lp-container">
        <div class="sec-eyebrow">{{ t('landingPage.sections.sectionA') }}</div>
        <h2 class="lp-h2">{{ t('landingPage.sections.sectionATitlePrefix') }} <span class="lp-accent">{{ t('landingPage.sections.sectionATitleAccent') }}</span></h2>
        <p class="lp-body">{{ t('landingPage.sectionABody') }} <router-link to="/trust-reputation" class="lp-inline-link">{{ t('landingPage.sectionATrustLink') }}</router-link></p>

        <!-- ─── ZKP ─── -->
        <div class="zkp-eyebrow-tag">{{ t('landingPage.zkp.eyebrow') }}</div>
        <h3 class="eng-h3">{{ t('landingPage.zkp.h3a') }}<span class="lp-accent">{{ t('landingPage.zkp.h3Accent') }}</span></h3>
        <p class="eng-body">{{ t('landingPage.zkp.body') }}</p>

        <div class="zkp-flow">
          <div class="zkp-col">
            <div class="zkp-col-label">{{ t('landingPage.zkp.agentSide') }}</div>
            <div class="zkp-box zkp-box-agent">
              <div class="zkp-region zkp-private">
                <div class="zkp-region-label"><Icon name="mdi:lock" /> {{ t('landingPage.zkp.privateWitness') }}</div>
                <code class="zkp-line">total_cost = 1000</code>
                <code class="zkp-line">salt = random</code>
                <div class="zkp-never">{{ t('landingPage.zkp.neverTransmitted') }}</div>
              </div>
              <div class="zkp-region zkp-public">
                <div class="zkp-region-label">{{ t('landingPage.zkp.publicInputs') }}</div>
                <code class="zkp-line">max_markup_bps = 3000</code>
                <code class="zkp-line">offered_price = 1200</code>
                <code class="zkp-line">context = offer ref</code>
              </div>
            </div>
            <div class="zkp-proof-chip">{{ t('landingPage.zkp.proofChip') }}</div>
          </div>

          <div class="zkp-arrow">
            <div class="zkp-arrow-line"></div>
            <div class="zkp-arrow-text">POST /attestations/submit<br><span class="zkp-arrow-sub">{ proof_bytes, public_inputs }</span></div>
            <div class="zkp-arrowhead">▶</div>
          </div>

          <div class="zkp-col">
            <div class="zkp-col-label">{{ t('landingPage.zkp.serverSide') }}</div>
            <div class="zkp-box zkp-box-registry">
              <div class="zkp-verify-step" v-for="step in zkpVerifySteps" :key="step.n">
                <span class="zkp-verify-n">{{ step.n }}</span>
                <span class="zkp-verify-text">{{ step.text }}</span>
              </div>
            </div>
            <div class="zkp-result">
              <span class="zkp-result-check">✓</span>
              <span class="zkp-result-text">{{ t('landingPage.zkp.resultText') }}</span>
            </div>
          </div>
        </div>

        <div class="zkp-circuits">
          <div class="zkp-circuit" v-for="circuit in zkpCircuits" :key="circuit.id">
            <div class="zkp-circuit-head">
              <span class="zkp-circuit-id">{{ circuit.id }}</span>
              <span class="zkp-circuit-scheme">UltraHonk · bb 0.82.2</span>
            </div>
            <p class="zkp-circuit-desc">{{ circuit.desc }}</p>
            <div class="zkp-circuit-io">
              <div class="zkp-io-col">
                <div class="zkp-io-label zkp-io-pub">{{ t('landingPage.zkp.publicInputs') }}</div>
                <code v-for="inp in circuit.publicInputs" :key="inp" class="zkp-io-item zkp-io-item-pub">{{ inp }}</code>
              </div>
              <div class="zkp-io-col">
                <div class="zkp-io-label zkp-io-priv">{{ t('landingPage.zkp.privateWitness') }}</div>
                <code v-for="inp in circuit.privateInputs" :key="inp" class="zkp-io-item zkp-io-item-priv"><Icon name="mdi:lock" /> {{ inp }}</code>
              </div>
            </div>
          </div>
        </div>

        <!-- ─── EigenTrust++ ─── -->
        <div class="eng-divider"></div>
        <div class="et-eyebrow-tag">{{ t('landingPage.eigen.eyebrow') }}</div>
        <h3 class="eng-h3">{{ t('landingPage.eigen.h3a') }}<span class="lp-accent">{{ t('landingPage.eigen.h3Accent') }}</span></h3>
        <p class="eng-body">{{ t('landingPage.eigen.body') }}</p>

        <div class="et-layout">
          <div class="et-algo">
            <div class="et-section-label">{{ t('landingPage.eigen.algoLabel') }}</div>
            <div class="et-steps">
              <div class="et-step" v-for="step in eigenSteps" :key="step.n">
                <div class="et-step-n">{{ step.n }}</div>
                <div>
                  <div class="et-step-name">{{ step.name }}</div>
                  <div class="et-step-desc">{{ step.desc }}</div>
                </div>
              </div>
            </div>
            <div class="et-formula-block">
              <div class="et-formula-label">POWER ITERATION FORMULA</div>
              <div class="et-formula">t<sup>(k+1)</sup> = (1&minus;&alpha;) &middot; C<sup>T</sup> &middot; t<sup>(k)</sup> + &alpha; &middot; p</div>
              <div class="et-formula-params">
                <span class="et-fparam"><em>&alpha;</em> = 0.15 teleportation</span>
                <span class="et-fparam"><em>C</em> = trust matrix</span>
                <span class="et-fparam"><em>p</em> = uniform prior</span>
              </div>
              <div class="et-converge">&Vert;t<sup>(k+1)</sup> &minus; t<sup>(k)</sup>&Vert;<sub>&infin;</sub> &lt; 10<sup>&minus;6</sup> &rarr; converged</div>
            </div>
          </div>

          <div class="et-right">
            <div class="et-section-label">TRUST SIGNALS</div>
            <div class="et-signals">
              <div class="et-signal" v-for="sig in trustSignals" :key="sig.event">
                <div :class="['et-dot', 'et-dot-' + sig.color]"></div>
                <div>
                  <div class="et-sig-event">{{ sig.event }}</div>
                  <div class="et-sig-effect">{{ sig.effect }}</div>
                </div>
              </div>
            </div>
            <div class="et-section-label" style="margin-top:1.5rem">SYBIL DEFENSES</div>
            <div class="et-defenses">
              <div class="et-defense" v-for="def in sybilDefenses" :key="def.name">
                <div class="et-def-name">{{ def.name }}</div>
                <div class="et-def-desc">{{ def.desc }}</div>
              </div>
            </div>
          </div>
        </div>

      </div>
    </section>

    <!-- ═══ SECTION B: PRICE, PUNISH, GOVERN ═══ -->

    <section class="lp-section">
      <div class="lp-container">
        <div class="sec-eyebrow sec-eyebrow-b">{{ t('landingPage.sectionB.eyebrow') }}</div>
        <h2 class="lp-h2">{{ t('landingPage.sectionB.h2a') }}<span class="lp-accent">{{ t('landingPage.sectionB.h2Accent') }}</span></h2>
        <p class="lp-body">{{ t('landingPage.sectionB.leadA') }}<router-link to="/units-and-fees" class="lp-inline-link">{{ t('landingPage.sectionB.leadDynFeeLink') }}</router-link>{{ t('landingPage.sectionB.leadB') }}<router-link to="/governance-docs" class="lp-inline-link">{{ t('landingPage.sectionB.leadGovLink') }}</router-link>{{ t('landingPage.sectionB.leadC') }}</p>

        <!-- ─── Membership and the commons (§MEMBERSHIP; replaces the veToken block, his word 2026-10-02) ───
             What runs is read from this registry (registry-config governance_weight_mode, governance_presence_mode,
             commons_enabled; GET /membership/stats). A switch that is off reads "not switched on for this registry
             yet", never as live: production governs by locks until BaFin answers and he says otherwise. -->
        <div class="vt-eyebrow-tag">{{ t('landingPage.membership.eyebrow') }}</div>
        <h3 class="eng-h3">{{ t('landingPage.membership.h3a') }}<span class="lp-accent">{{ t('landingPage.membership.h3Accent') }}</span></h3>
        <p v-if="memberMode !== 'unknown'" class="eng-body">{{ memberMode === 'member' ? t('landingPage.membership.leadOn') : t('landingPage.membership.leadPlanned') }}</p>
        <ReadFailedNotice v-if="cfgReadFailed" :retry="cfgReload" />
        <div v-if="memberMode !== 'unknown'" class="mb-status" data-testid="lp-membership-status" :data-mode="memberMode">
          <span class="mb-status-dot" :class="{ 'mb-status-dot--on': memberMode === 'member' }" aria-hidden="true"></span>
          <span v-if="memberMode === 'member'">{{ memberStats ? t('landingPage.membership.statusOnCount', { n: memberStats.members }) : t('landingPage.membership.statusOn') }}</span>
          <span v-else>{{ t('landingPage.membership.statusPlanned') }}</span>
        </div>
        <div class="mb-grid">
          <div class="mb-card">
            <h4 class="mb-card-title">{{ t('landingPage.membership.joinTitle') }}</h4>
            <p class="mb-card-body">{{ memberMinDays ? t('landingPage.membership.joinBodyDays', { days: memberMinDays }) : t('landingPage.membership.joinBody') }}</p>
          </div>
          <div class="mb-card">
            <h4 class="mb-card-title">{{ t('landingPage.membership.voteTitle') }}</h4>
            <p class="mb-card-body">{{ memberTenureDays === 365 ? t('landingPage.membership.voteBodyYear', { max: memberMaxWeight }) : t('landingPage.membership.voteBodyDays', { max: memberMaxWeight, days: memberTenureDays }) }}</p>
            <p v-if="presenceOn" class="mb-card-body">{{ t('landingPage.membership.voteHuman') }}</p>
          </div>
          <div class="mb-card" data-testid="lp-commons-card" :data-on="commonsOn ? '1' : '0'">
            <h4 class="mb-card-title">{{ t('landingPage.membership.commonsTitle') }} <span v-if="cfgReadOk" class="mb-chip" :class="{ 'mb-chip--on': commonsOn }">{{ commonsOn ? t('landingPage.membership.commonsOn') : t('landingPage.membership.commonsPlanned') }}</span></h4>
            <p class="mb-card-body">{{ t('landingPage.membership.commonsBody') }}</p>
          </div>
        </div>
        <p class="mb-foot">{{ t('landingPage.membership.foot') }}</p>

        <!-- ─── Transaction Fees ─── -->
        <div class="eng-divider"></div>
        <div class="fee-eyebrow-tag">{{ t('landingPage.fee.eyebrow') }}</div>
        <h3 class="eng-h3">{{ t('landingPage.sectionB.feeH3a') }}<span class="lp-accent">{{ t('landingPage.sectionB.feeH3Accent') }}</span></h3>
        <p class="eng-body">{{ t('landingPage.sectionB.feeBodyA') }}<router-link to="/units-and-fees" class="lp-inline-link">{{ t('landingPage.sectionB.feeBodyLink') }}</router-link></p>

        <div class="fee-layout">
          <div class="fee-formula-col">
            <div class="fee-formula-label">DYNAMIC RATE</div>
            <div class="fee-formula">fee_rate = base_rate + velocity_factor &times; scaling</div>
            <div class="fee-clamp">{{ t('landingPage.sectionB.feeClamp') }}</div>
            <div class="fee-params">
              <div class="fee-param" v-for="p in feeParams" :key="p.label">
                <span class="fee-plabel">{{ p.label }}</span>
                <span class="fee-pval">{{ p.val }}</span>
                <span class="fee-pdesc">{{ p.desc }}</span>
              </div>
            </div>
            <div class="fee-example">{{ t('landingPage.sectionB.feeExample', { unit }) }}</div>
          </div>

          <div class="fee-flow-col">
            <div class="fee-flow-label">FEE FLOW</div>
            <div class="fee-flow">
              <div class="fee-flow-step" v-for="(step, i) in feeFlowSteps" :key="i">
                <div class="fee-flow-node" :class="step.nodeClass">{{ step.node }}</div>
                <div v-if="i < feeFlowSteps.length - 1" class="fee-flow-arrow">↓</div>
              </div>
            </div>
            <div class="fee-exempt">
              <span class="fee-exempt-label">FEE-EXEMPT</span>
              <span class="fee-exempt-item" v-for="e in feeExemptions" :key="e">{{ e }}</span>
            </div>
          </div>
        </div>

        <!-- ─── Enforcement Engine ─── -->
        <div class="eng-divider"></div>
        <div class="enf-eyebrow-tag">{{ t('landingPage.sectionB.enfEyebrow') }}</div>
        <h3 class="eng-h3">{{ t('landingPage.sectionB.enfH3a') }}<span class="lp-accent">{{ t('landingPage.sectionB.enfH3Accent') }}</span></h3>
        <p class="eng-body">{{ t('landingPage.sectionB.enfBody') }}</p>

        <div class="enf-layout">

          <!-- Bond -->
          <div class="enf-block">
            <div class="enf-block-eyebrow">{{ t('landingPage.sectionB.bondEyebrow') }}</div>
            <div class="enf-block-title">{{ t('landingPage.sectionB.bondTitle') }}</div>
            <p class="enf-block-body">{{ t('landingPage.sectionB.bondBody') }}</p>
            <div class="enf-bond-conditions">
              <div class="enf-bond-cond" v-for="cond in bondConditions" :key="cond.label">
                <span class="enf-bond-val">{{ cond.val }}</span>
                <span class="enf-bond-label">{{ cond.label }}</span>
              </div>
            </div>
          </div>

          <!-- Escalation Ladder -->
          <div class="enf-block">
            <div class="enf-block-eyebrow">{{ t('landingPage.sectionB.ladderEyebrow') }}</div>
            <div class="enf-block-title">{{ t('landingPage.sectionB.ladderTitle') }}</div>
            <div class="enf-ladder">
              <div class="enf-rung" v-for="rung in enfLadder" :key="rung.offense">
                <div class="enf-rung-offense" :class="'enf-offense-' + rung.severity">{{ rung.offense }}</div>
                <div class="enf-rung-actions">
                  <span class="enf-action" v-for="action in rung.actions" :key="action" :class="'enf-action-' + rung.severity">{{ action }}</span>
                </div>
              </div>
            </div>
            <div class="enf-ladder-note">{{ t('landingPage.sectionB.ladderNote') }}</div>
          </div>

        </div>
      </div>
    </section>

    <!-- ═══ EVERY RULE IS A SETTING (§LANDINGTRUTH, his word 2026-10-02 "approved, go with b") ═══
         The values this page shows are this network's settings; each registry publishes the ones it runs (signed card:
         fees, bond, voting thresholds; public settings: membership, the commons, the grant). "Held by the network" is
         read from the card (fees.*.locked_by_network), never assumed: a standalone frame running this page says no such
         thing. No payout rate, euro price or euro sale is named (agentvault2-5b). -->
    <section class="lp-section" data-testid="lp-settings">
      <div class="lp-container">
        <div class="sec-eyebrow">{{ t('landingPage.settings.eyebrow') }}</div>
        <h2 class="lp-h2">{{ t('landingPage.settings.h2a') }}<span class="lp-accent">{{ t('landingPage.settings.h2Accent') }}</span></h2>
        <p class="lp-body">{{ t('landingPage.settings.lead') }}</p>
        <div class="mb-grid">
          <div class="mb-card">
            <h3 class="mb-card-title">{{ t('landingPage.settings.hereTitle') }}</h3>
            <p class="mb-card-body">{{ t('landingPage.settings.hereBody') }}</p>
            <p v-if="cardFeesHeld" class="mb-card-body" data-testid="lp-settings-held">{{ t('landingPage.settings.hereHeld') }}</p>
          </div>
          <div class="mb-card">
            <h3 class="mb-card-title">{{ t('landingPage.settings.soloTitle') }}</h3>
            <p class="mb-card-body">{{ t('landingPage.settings.soloBody') }}</p>
          </div>
          <div class="mb-card">
            <h3 class="mb-card-title">{{ t('landingPage.settings.ownTitle') }}</h3>
            <p class="mb-card-body">{{ t('landingPage.settings.ownBody') }}</p>
          </div>
        </div>
        <p class="mb-foot">{{ t('landingPage.settings.foot') }}</p>
        <p class="st-links">
          <a href="/.well-known/registry-card.json" target="_blank" rel="noopener" class="lp-inline-link">{{ t('landingPage.settings.linkCard') }}</a>
          <a href="/api/v1/public/registry-config" target="_blank" rel="noopener" class="lp-inline-link">{{ t('landingPage.settings.linkConfig') }}</a>
        </p>
      </div>
    </section>

    <!-- How Agents Work -->

    <section class="lp-section">
      <div class="lp-container">
        <div class="sec-eyebrow sec-eyebrow-c">{{ t('landingPage.sectionC.eyebrow') }}</div>
        <h2 class="lp-h2">{{ t('landingPage.sectionC.h2a') }}<span class="lp-accent">{{ t('landingPage.sectionC.h2Accent') }}</span></h2>
        <p class="lp-body">{{ t('landingPage.sectionC.lead') }}</p>

        <!-- Network Capacity Bar -->
        <div class="op-capacity-bar">
          <div class="op-cap-item">
            <div class="op-cap-val">3,000–5,000</div>
            <div class="op-cap-label">{{ t('landingPage.sectionC.capA') }}</div>
          </div>
          <div class="op-cap-divider"></div>
          <div class="op-cap-item">
            <div class="op-cap-val">100,000+</div>
            <div class="op-cap-label">{{ t('landingPage.sectionC.capB') }}</div>
          </div>
          <div class="op-cap-divider"></div>
          <div class="op-cap-item">
            <div class="op-cap-val">9</div>
            <div class="op-cap-label">{{ t('landingPage.sectionC.capC') }}</div>
          </div>
        </div>

        <!-- Mission CTA Card -->
        <div class="op-apply-cta">
          <div class="op-mission-compact">
            <h3 class="op-apply-title">{{ t('landingPage.sectionC.freeTitle') }}</h3>
            <p class="op-apply-sub" style="max-width: 540px; margin: 0 auto 18px;">{{ t('landingPage.sectionC.freeSub') }}</p>
            <div class="op-mission-stats">
              <div class="op-mission-stat"><span class="op-mission-stat-val">$0</span><span class="op-mission-stat-lbl">{{ t('landingPage.sectionC.statLicense') }}</span></div>
              <div class="op-mission-stat"><span class="op-mission-stat-val">0%</span><span class="op-mission-stat-lbl">{{ t('landingPage.sectionC.statRevenue') }}</span></div>
              <div class="op-mission-stat"><span class="op-mission-stat-val">100%</span><span class="op-mission-stat-lbl">{{ t('landingPage.sectionC.statYours') }}</span></div>
              <div class="op-mission-stat"><span class="op-mission-stat-val" style="color:var(--nc-primary);">3</span><span class="op-mission-stat-lbl">{{ t('landingPage.sectionC.statDeploy') }}</span></div>
            </div>
            <div style="display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; margin-top: 20px;">
              <router-link to="/operator?tab=cloud" class="lp-cta op-apply-btn" data-testid="lp-cta-cloud" style="background: rgba(var(--nc-primary-rgb),0.15); border: 1px solid rgba(var(--nc-primary-rgb),0.4); color: var(--nc-primary);">
                <span>{{ t('landingPage.sectionC.ctaCloud') }}</span>
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M3 8h10m0 0L9 4m4 4L9 12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
              </router-link>
              <router-link to="/operator?tab=self-hosted" class="lp-cta op-apply-btn" data-testid="lp-cta-apply">
                <span>{{ t('landingPage.sectionC.ctaApply') }}</span>
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M3 8h10m0 0L9 4m4 4L9 12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
              </router-link>
              <router-link to="/operator-docs" class="lp-cta op-apply-btn" style="background: rgba(59,130,246,0.1); border: 1px solid rgba(59,130,246,0.4); color: #3B82F6;">
                <span>{{ t('landingPage.sectionC.ctaDocs') }}</span>
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M3 8h10m0 0L9 4m4 4L9 12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
              </router-link>
              <router-link to="/frame-commander" class="lp-cta op-apply-btn" data-testid="lp-cta-request-frame" style="background: transparent; border: 1px solid rgba(var(--nc-primary-rgb),0.3); color: rgba(var(--nc-primary-rgb),0.9);">
                <span>{{ t('landingPage.sectionC.ctaFrame') }}</span>
              </router-link>
              <router-link to="/operator" class="lp-cta op-apply-btn" style="background: transparent; border: 1px solid rgba(var(--nc-primary-rgb),0.3); color: rgba(var(--nc-primary-rgb),0.9);">
                <span>{{ t('landingPage.sectionC.ctaDetails') }}</span>
              </router-link>
            </div>
          </div>
        </div>

        <div class="op-layout">

          <!-- Federation Pathway -->
          <div class="op-steps-col">
            <div class="op-col-label">{{ t('landingPage.sectionC.pathwayLabel') }}</div>
            <div class="op-steps">
              <div class="op-step" v-for="step in operatorSteps" :key="step.n">
                <div class="op-step-n">{{ step.n }}</div>
                <div>
                  <div class="op-step-name">{{ step.name }}</div>
                  <div class="op-step-desc">{{ step.desc }}</div>
                </div>
              </div>
            </div>

            <div class="op-invariant">
              <div class="op-invariant-label">{{ t('landingPage.sectionC.invariantLabel') }}</div>
              <div class="op-invariant-formula">Issued &minus; Destroyed + Transit == &Sigma; ALL balances</div>
              <div class="op-invariant-steps">
                <div class="op-inv-step" v-for="s in invariantSteps" :key="s.n">
                  <span class="op-inv-n">{{ s.n }}</span>
                  <span class="op-inv-text">{{ s.text }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Operator Dimensions -->
          <div class="op-dims-col">
            <div class="op-col-label">{{ t('landingPage.sectionC.ownsLabel') }}</div>
            <div class="op-dims">
              <div class="op-dim" v-for="dim in operatorDims" :key="dim.label">
                <div class="op-dim-label">{{ dim.label }}</div>
                <div class="op-dim-val">{{ dim.val }}</div>
              </div>
            </div>

            <div class="op-sovereignty">
              <div class="op-sov-head">
                <span class="op-sov-mark">◈</span>
                <span class="op-sov-title">{{ t('landingPage.sectionC.sovTitle') }}</span>
              </div>
              <p class="op-sov-body">{{ t('landingPage.sectionC.sovBody') }}</p>
              <div class="op-sov-tag-row">
                <span class="op-sov-tag" v-for="tag in sovereigntyTags" :key="tag">{{ tag }}</span>
              </div>
            </div>
          </div>

        </div>
      </div>
    </section>

    <!-- ═══ YOUR REGISTRY SHIPS WITH ═══ -->

    <section class="lp-section">
      <div class="lp-container">
        <h3 class="lp-h3 lp-center" style="margin-bottom: 2rem;">{{ t('landingPage.sectionC.shipsHeader') }}</h3>
        <div class="op-ships-grid">
          <div class="op-ships-item" v-for="item in registryShipsWith" :key="item">
            <span class="op-ships-check">&#10003;</span>
            <span>{{ item }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- ═══ BETA OPERATOR PROGRAM ═══ -->

    <section class="lp-section" style="border-top: 1px solid rgba(var(--nc-primary-rgb),0.08);">
      <div class="lp-container lp-center">
        <div class="op-beta-program">
          <div class="sec-eyebrow" style="color: var(--nc-primary);">{{ t('landingPage.betaProg.eyebrow') }}</div>
          <h2 class="lp-h2" style="margin-top: 0.5rem;">{{ t('landingPage.betaProg.title') }}</h2>
          <p class="lp-body" style="max-width: 640px; margin: 0 auto 2rem;">{{ t('landingPage.betaProg.lead') }}</p>

          <div class="op-beta-cols">
            <div class="op-beta-col">
              <div class="op-beta-col-title">{{ t('landingPage.betaProg.getTitle') }}</div>
              <ul class="op-beta-list">
                <li>{{ t('landingPage.betaProg.get1') }}</li>
                <li>{{ t('landingPage.betaProg.get2') }}</li>
                <li>{{ t('landingPage.betaProg.get3') }}</li>
                <li>{{ t('landingPage.betaProg.get4') }}</li>
                <li>{{ t('landingPage.betaProg.get5') }}</li>
              </ul>
            </div>
            <div class="op-beta-col">
              <div class="op-beta-col-title">{{ t('landingPage.betaProg.needTitle') }}</div>
              <ul class="op-beta-list">
                <li>{{ t('landingPage.betaProg.need1') }}</li>
                <li>{{ t('landingPage.betaProg.need2') }}</li>
                <li>{{ t('landingPage.betaProg.need3') }}</li>
                <li>{{ t('landingPage.betaProg.need4') }}</li>
              </ul>
            </div>
          </div>

          <router-link to="/operator?tab=cloud" class="lp-cta" data-testid="lp-cta-operator-program" style="margin-top: 2rem;">
            <span>{{ t('landingPage.betaProg.cta') }}</span>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M3 8h10m0 0L9 4m4 4L9 12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </router-link>
        </div>
      </div>
    </section>

    <!-- Beta Notice -->

    <section class="lp-section lp-section-dark">
      <div class="lp-container lp-center">
        <div class="lp-beta-card">
          <div class="lp-beta-badge">{{ t('landingPage.betaNotice.badge') }}</div>
          <h2 class="lp-h2" style="margin-bottom: 1rem;">{{ t('landingPage.betaNotice.title') }}</h2>
          <p class="lp-body" style="max-width: 640px; margin: 0 auto;">{{ t('landingPage.betaNotice.body') }}</p>
          <div class="lp-beta-facts">
            <span>{{ t('landingPage.betaNotice.factA') }}</span><span class="lp-dot">·</span>
            <span>{{ t('landingPage.betaNotice.factB') }}</span><span class="lp-dot">·</span>
            <span>{{ t('landingPage.betaNotice.factC') }}</span><span class="lp-dot">·</span>
            <span>{{ t('landingPage.betaNotice.factD') }}</span>
          </div>
          <div class="lp-beta-wipe">
            <span class="lp-beta-wipe-label">{{ t('landingPage.betaNotice.wipeLabel') }}</span>
            {{ t('landingPage.betaNotice.wipeBody') }}
          </div>
          <button @click="getStarted" class="lp-cta" style="margin-top: 2rem;">
            <span>{{ t('landingPage.betaNotice.cta') }}</span>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M3 8h10m0 0L9 4m4 4L9 12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
        </div>
      </div>
    </section>

    <!-- Footer -->

    <footer class="lp-footer">
      <div class="lp-container">
        <div class="lp-footer-top">
          <div class="lp-footer-brand">
            <span class="lp-footer-name">THE PROTOCOL</span>
            <span class="lp-footer-tagline">{{ t('landingPage.footer.tagline') }}</span>
          </div>
          <div class="lp-footer-links">
            <RouterLink to="/docs">{{ t('landingPage.footer.docs') }}</RouterLink>
            <RouterLink to="/status" data-testid="lp-footer-status">{{ t('landingPage.footer.status', 'Status') }}</RouterLink>
            <RouterLink to="/pricing">{{ t('landingPage.footer.pricing', 'Pricing') }}</RouterLink>
            <RouterLink to="/contact">{{ t('landingPage.footer.contact', 'Contact') }}</RouterLink>
            <RouterLink to="/legal/terms">{{ t('landingPage.footer.terms') }}</RouterLink>
            <RouterLink to="/legal/privacy">{{ t('landingPage.footer.privacy') }}</RouterLink>
            <RouterLink to="/legal/disclaimer">{{ t('landingPage.footer.disclaimer') }}</RouterLink>
            <RouterLink to="/legal/cookies">{{ t('landingPage.footer.cookies') }}</RouterLink>
            <RouterLink to="/legal/sla">{{ t('landingPage.footer.sla') }}</RouterLink>
            <RouterLink to="/legal/dpa">{{ t('landingPage.footer.dpa') }}</RouterLink>
            <RouterLink to="/legal/imprint">{{ t('landingPage.footer.imprint') }}</RouterLink>
          </div>
        </div>
        <div class="lp-footer-bottom">
          <span>{{ t('landingPage.footer.copyright') }}</span>
        </div>
      </div>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, computed, watch, nextTick, onMounted, onUnmounted, defineAsyncComponent } from 'vue'
import { useRouter } from 'vue-router'
import { esStatsUrl, FRAMES } from '@/config/frames'  // §FEFRAME W2: the frames and their stats come from the frame manifest
// §FEDEVENTS-4: card-truth LOCAL currency for the single-frame solo pane — the
// chip was hardcoded to Frame A's currency, so a standalone frame (hetzner)
// showed "AVT" over its own correctly-named ledger. Public endpoints only.
import { useFrames } from '@/composables/useFrames'
// §SHOWCASEGATE — one shared read of /public/registry-config (module-cached; N callers = 1 request).
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { governanceMode, presenceMode, commonsEnabled, type MembershipStats } from '@/services/membership/membership'
import { useShowcaseRoster } from '@/composables/useShowcaseRoster'
import { registryBase, mcpEndpoints, sdkSnippetHost } from '@/services/frameHost'
const { localCurrency: efLocalCurrency, frames: efFrames, localRegistryName: efRegistryName, localTrustDomain: efTrustDomain } = useFrames()
// §SHOWCASEGATE — the showcase band mounts only where the server says the visitor rail works.
const { showcaseChatEnabled, trustDomain: cfgTrustDomain, journalEnabled, config: regCfg, localCurrency: cfgCurrency, readOk: cfgReadOk, readFailed: cfgReadFailed, reload: cfgReload } = useRegistryConfig()

// §LANDINGTRUTH (2026-10-02, his word): the units, the starting grant, membership and the commons are read from what
// this registry says (registry-config, the frame manifest, GET /membership/stats), never from a literal; a switch
// that is off reads "not switched on for this registry yet", never as live.
const unit = computed(() => efLocalCurrency.value || cfgCurrency.value || t('landingPage.unitsFallback'))
const liveFrames = computed(() => (efFrames.value || []).filter(f =>
  !f.isSandbox && f.strip !== 'sandbox' && !!f.currency && (f.tier === 'mainframe' || f.tier === 'sovereign-mainframe')))
const frameUnitsList = computed(() => {
  const own = liveFrames.value.map(f => t('landingPage.token.unitOnFrame', { unit: f.currency, frame: f.label }))
  if (own.length) return own.join(', ')
  const name = efRegistryName.value || ''
  return name ? t('landingPage.token.unitOnFrame', { unit: unit.value, frame: name }) : unit.value
})
const frameUnitsSlash = computed(() => {
  const cur = [...new Set(liveFrames.value.map(f => f.currency))]
  return cur.length > 1 ? cur.join('/') : unit.value
})
const grantAmount = computed(() => {
  const n = Number(regCfg.value.genesis_grant_amount)
  return regCfg.value.genesis_grant_enabled === true && Number.isFinite(n) && n > 0 ? n : 0
})
const grantText = computed(() => (grantAmount.value ? new Intl.NumberFormat(appLocale()).format(grantAmount.value) : ''))
// §LANDINGTRUTH (30): 'unknown' until the registry has answered (an unread config reads as lock, which is false on a
// member-mode registry): the block states no mode then, and says so if the read failed
const memberMode = computed(() => (cfgReadOk.value ? governanceMode(regCfg.value) : 'unknown'))
const presenceOn = computed(() => memberMode.value === 'member' && presenceMode(regCfg.value) !== 'off')
const commonsOn = computed(() => commonsEnabled(regCfg.value))
// §MEMBERSHIP D2 (FEDERATION_BALLOT_MODE): federation-wide proposals decided by one ballot per registry; the governance
// step says so where it runs instead of calling it planned (V0563, his word 2026-10-03: ballots on the production frames)
const ballotsOn = computed(() => regCfg.value.federation_ballot_mode === true)
const memberStats = ref<MembershipStats | null>(null)
const memberMinDays = computed(() => memberStats.value?.min_bond_age_days ?? 0)
const memberMaxWeight = computed(() => memberStats.value?.max_weight || 2)
const memberTenureDays = computed(() => memberStats.value?.tenure_full_days || 365)
const cardFeesHeld = ref(false)
async function loadCardFees() {
  try {
    const res = await fetch(`${window.location.origin}/.well-known/registry-card.json`, { cache: 'no-store' })
    if (!res.ok) return // no card: the "held by the network" sentence is left out, never guessed
    const c = await res.json()
    const f = c && typeof c === 'object' ? c.fees : null
    cardFeesHeld.value = !!(f && (f.intra_registry?.locked_by_network === true || f.cross_registry?.locked_by_network === true))
  } catch { /* left out */ }
}
async function loadMemberStats() {
  try {
    const res = await fetch(`${window.location.origin}/api/v1/membership/stats`, { cache: 'no-store' })
    if (!res.ok) return // a registry without the route: the copy then names no numbers
    const d = await res.json()
    if (d && typeof d === 'object' && typeof d.members === 'number') memberStats.value = d as MembershipStats
  } catch { /* the copy without numbers stands */ }
}
// §FRESHFRAME (2026-09-14) — the page notices where it is: every address a visitor copies or types is
// derived from the host serving the page (services/frameHost.ts, unit-tested; the apex publishes the
// flagship's documented api. address, every other host itself), the SDK snippets print this frame's
// registry and trust domain, and the sovereign roster renders only where the server says the showcase
// catalog is this deployment's.
const lpOrigin = typeof window !== 'undefined' ? window.location.origin : ''
const lpRegistryBase = registryBase(lpOrigin)
const mcp = mcpEndpoints(lpRegistryBase)
const sdk = computed(() => sdkSnippetHost(lpRegistryBase, cfgTrustDomain.value))
// §LANDINGTRUTH (his words 2026-10-02 "it always has the identifier"): every DID on this page names the frame that
// minted it, did:theprotocol:<issuer>:<uuid4>, and the issuer is the registry's SPIFFE trust domain (EU's host is
// theprotocol.cloud, its DIDs say eu.theprotocol.cloud), so it is read from the registry, never from the page's host;
// "<frame>" stands in until the registry has answered.
const didIssuer = computed(() => ((cfgTrustDomain.value || efTrustDomain.value || '') + '').trim().toLowerCase() || '<frame>')
const { decision: roster } = useShowcaseRoster()
import DOMPurify from 'dompurify'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import { setLocale as i18nSetLocale } from '@/i18n'
dayjs.extend(relativeTime)

/**
 * 🔴 §LOCALESWEEP — A BREAKPOINT THAT IS MEASURED, NOT GUESSED.
 *
 * Translating the landing page into German made the nav ~40% longer, and the hamburger
 * breakpoint is a hardcoded 1023.98px. MEASURED on the real page: in German at 1440px,
 * ANMELDEN, REGISTRIEREN **and the language picker itself** all sat past the right edge —
 * so a German visitor on a common laptop could not reach Register, Log in, or the control
 * that would switch the language back. (English overflowed by 17px; German by 320px.)
 *
 * The CSS already tried to solve this with guessed widths and says so in its own comment
 * ("richer locales (Chinese 注册中心, Russian РЕГИСТР)"), tightening between 1024 and
 * 1439 — and then STOPPING at exactly the width where German is worst. Guessing a pixel
 * value per language is a losing game; ask the layout instead.
 *
 * Two stages, and never a loop: `tight` re-uses the existing tightening at ANY width;
 * `burger` shows the mobile drawer, which already holds every link. Hysteresis is on the
 * VIEWPORT width, not on the element — in burger mode `.lp-nav-right` becomes a fixed
 * drawer, so its own width no longer means anything and must not be re-measured.
 */
const lpNavRightRef = ref<HTMLElement | null>(null)
const lpNavFit = ref<'wide' | 'tight' | 'burger'>('wide')
let lpNavRO: ResizeObserver | null = null
let lpNavTimer: any = null
let lpNavBusy = false

/**
 * ⚠ ONE DECISION FROM ONE MEASUREMENT, never a step per observer tick.
 *
 * The first cut advanced one stage per ResizeObserver callback (wide → tight → burger).
 * A ResizeObserver fires SEVERAL times during initial layout, so the nav walked straight
 * to `burger` at 1920px — where it had room to spare — and could not come back, because
 * the exit condition was a growing viewport that never grew. MEASURED: need=319,
 * avail=953, mode=burger.
 *
 * So: always start from `wide`, let the DOM settle, measure, and if it does not fit try
 * `tight` and measure that too. The mode is a pure function of the measurement, which
 * means it cannot oscillate and cannot get stuck.
 */
async function lpEvaluateNav() {
  const right = lpNavRightRef.value
  if (!right || lpNavBusy) return
  if (window.innerWidth < 1024) { lpNavFit.value = 'wide'; return }  // the media query owns it
  lpNavBusy = true
  try {
    const fits = () => {
      const inner = right.parentElement
      if (!inner) return true
      const brand = inner.querySelector('.lp-brand') as HTMLElement | null
      const avail = inner.clientWidth - (brand ? brand.getBoundingClientRect().width : 0) - 36
      return right.scrollWidth <= avail
    }
    lpNavFit.value = 'wide'
    await nextTick()
    if (fits()) return
    lpNavFit.value = 'tight'
    await nextTick()
    if (fits()) return
    lpNavFit.value = 'burger'
  } finally {
    // Released on the next frame so the class change we just made cannot re-enter through
    // the observer it is about to trigger.
    requestAnimationFrame(() => { lpNavBusy = false })
  }
}
function lpMeasureNav() {
  clearTimeout(lpNavTimer)
  lpNavTimer = setTimeout(() => { void lpEvaluateNav() }, 120)
}

// ── Mobile nav + language picker ────────────────────────────────────────
const lpNavOpen = ref(false)
const lpLangOpen = ref(false)
const lpLangRef = ref<HTMLElement | null>(null)

import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/composables/useI18n'
import LandingDiscovery from '@/components/landing/LandingDiscovery.vue'
import ProtocolMark from '@/components/ProtocolMark.vue'
import GlitchOverlay from '@/components/GlitchOverlay.vue'
import ExchangeTicker from '@/components/exchange/ExchangeTicker.vue'
import McSection from '@/components/dashboard/McSection.vue'
import { useLedgerStream, stripHasFrames } from '@/composables/useLedgerStream'
const McLedger = defineAsyncComponent(() => import('@/components/dashboard/McLedger.vue'))
import { useThemeFlash } from '@/composables/useThemeFlash'
import { useLogger } from '@/composables/useLogger'
import FlareEncirclement from '@/components/common/FlareEncirclement.vue'
import Icon from '@/components/Icon.vue'

// §pass39 (2026-05-18) — Total sovereign agents currently rendered in the
// gallery. Bumped each time a new sovereign ships. Drives the headline
// "{count, plural, one {# autonomous agent} other {# autonomous agents}}"
// at agents-section title. Wave-1 (6) + Wave-2 (5) + Hagrid (§pass42b) = 12, less Greedy Gregory, off the public pages
// until he is reworked (his word 2026-10-25, "yes all approved.": a lock-yield optimizer the network does not offer) = 11.
const SOVEREIGN_COUNT = 11
import { flagEmoji } from '@/utils/countries'

const log = useLogger('LandingPage')

// Cinematic neural → sovereign glitch on landing page mount.
// Once per browser tab (sessionStorage-gated); respects prefers-reduced-motion.
const { intensity: glitchIntensity, phase: glitchPhase, start: startGlitch } = useThemeFlash({ oncePerTab: true })
onMounted(() => startGlitch())

const AgentWorldGlobe = defineAsyncComponent(() =>
  import('@/views/AgentWorldCesium.vue')
)
// §SHOWCASEFED — below the fold, so it is loaded lazily like the globe above
// rather than added to the landing entry chunk.
const ShowcaseChat = defineAsyncComponent(() =>
  import('@/components/landing/ShowcaseChat.vue')
)
const globeLoaded = ref(false)

const router = useRouter()
const authStore = useAuthStore()
const { t, locale: lpLocale, availableLocales: lpAvailableLocales, tp } = useI18n()
function lpSelectLocale(code: any) {
  i18nSetLocale(code as any)
  lpLangOpen.value = false
}

function lpDocClickClose(e: MouseEvent) {
  if (lpLangRef.value && !lpLangRef.value.contains(e.target as Node)) {
    lpLangOpen.value = false
  }
}
onMounted(() => document.addEventListener('click', lpDocClickClose))

// ⚠ Observe the nav AND re-measure when the locale changes: switching language is exactly
// the event that changes how much room the nav needs, and it fires no resize.
onMounted(() => {
  lpMeasureNav()
  if (typeof ResizeObserver !== 'undefined' && lpNavRightRef.value?.parentElement) {
    lpNavRO = new ResizeObserver(() => lpMeasureNav())
    lpNavRO.observe(lpNavRightRef.value.parentElement)
  }
  window.addEventListener('resize', lpMeasureNav)
})
onUnmounted(() => { lpNavRO?.disconnect(); lpNavRO = null; window.removeEventListener('resize', lpMeasureNav) })
watch(lpLocale, () => lpMeasureNav())
onUnmounted(() => document.removeEventListener('click', lpDocClickClose))
if (authStore.isAuthenticated) router.push('/mission-control')
const getStarted = () => router.push(authStore.isAuthenticated ? '/mission-control' : '/register')

// ═══════════════ BETA ACCESS REQUEST ═══════════════

// 2026-05-07 audit: removed ~70 LOC of dead beta-access state + countdown +
// submitBetaRequest function. The /api/v1/beta/request-access endpoint was
// deprecated server-side (commented out in main.py:82,675) and the template
// no longer references the betaSubmitted/betaError/countdown refs. The
// 1Hz countdown setInterval was wasted CPU on every landing-page view.

function copyUrl(url: string, event: MouseEvent) {
  navigator.clipboard.writeText(url).then(() => {
    const btn = event.currentTarget as HTMLElement
    const orig = btn.style.borderColor
    btn.style.borderColor = 'rgba(16, 220, 129, 0.6)'
    setTimeout(() => { btn.style.borderColor = orig }, 1200)
  }).catch(() => {})
}

// ═══════════════ HEALTH WALL ═══════════════

interface ServiceStatus {
  name: string; port: number; url: string
  status: 'pending' | 'healthy' | 'down'; ms: number | null; failCount: number
  publicUrl?: string | null
}

// Health wall — production-safe: all checks go through the registry API proxy
// at /admin/service-health, so no direct port access from the browser is needed.
// Fallback: try same-origin path first, then direct port for localhost/dev.
const coreServiceDefs = [
  { name: 'Registry A', port: 8000, path: '/health' },
  { name: 'TEG Layer A', port: 8100, path: '/health' },
  { name: 'Event Store', port: 8200, path: '/health' },
  { name: 'OPA Engine', port: 8288, path: '/health' },
]

const serviceTiles = computed(() => [
  { icon: '☀', name: t('landingPage.serviceTiles.weather'),  price: '0.5', color: '#3b82f6' },
  { icon: '₿', name: t('landingPage.serviceTiles.currency'), price: '0.5', color: '#f59e0b' },
  { icon: '🔐', name: t('landingPage.serviceTiles.sslCheck'), price: '1.0', color: '#10b981' },
  { icon: '⏱', name: t('landingPage.serviceTiles.timezone'), price: '0.1', color: '#8b5cf6' },
  { icon: '📐', name: t('landingPage.serviceTiles.units'),    price: '0.1', color: '#ec4899' },
  { icon: '📰', name: t('landingPage.serviceTiles.news'),     price: '0.5', color: '#f43f5e' },
  { icon: '🌐', name: t('landingPage.serviceTiles.ipLookup'), price: '0.1', color: '#14b8a6' },
  { icon: '⏰', name: t('landingPage.serviceTiles.cron'),     price: '0.1', color: '#f97316' },
  { icon: '🔑', name: t('landingPage.serviceTiles.password'), price: '0.1', color: '#ef4444' },
  { icon: '📝', name: t('landingPage.serviceTiles.text'),     price: '0.1', color: '#6366f1' },
  { icon: '📄', name: t('landingPage.serviceTiles.converter'),price: '0.1', color: '#a855f7' },
])

const isLocalDev = ['localhost', '127.0.0.1'].includes(window.location.hostname)
const services = ref<ServiceStatus[]>(
  coreServiceDefs.map(d => ({
    name: d.name, port: d.port,
    url: isLocalDev
      ? `${window.location.protocol}//${window.location.hostname}:${d.port}${d.path}`
      : `${window.location.origin}${d.path}`,
    status: 'pending', ms: null, failCount: 0, publicUrl: null,
  }))
)
// Operator registries — populated dynamically from stack-health backend
const operatorServices = ref<ServiceStatus[]>([])

const lastCheckTime = ref<Date | null>(null)
let healthPoll: ReturnType<typeof setInterval> | null = null

const allServices = computed(() => [...services.value, ...operatorServices.value])
const healthyCount = computed(() => allServices.value.filter(s => s.status === 'healthy').length)
const unhealthyCount = computed(() => allServices.value.filter(s => s.status === 'down').length)
const overallHealthy = computed(() => unhealthyCount.value === 0 && healthyCount.value > 0)
const avgResponseTime = computed(() => {
  const w = allServices.value.filter(s => s.ms !== null)
  return w.length ? Math.round(w.reduce((a, s) => a + (s.ms || 0), 0) / w.length) : 0
})
const coreHealthyCount = computed(() => services.value.filter(s => s.status === 'healthy').length)
const opHealthyCount = computed(() => operatorServices.value.filter(s => s.status === 'healthy').length)
const opAvgResponseTime = computed(() => {
  const w = operatorServices.value.filter(s => s.ms !== null)
  return w.length ? Math.round(w.reduce((a, s) => a + (s.ms || 0), 0) / w.length) : 0
})
const heroStats = computed(() => {
  const stats = ledgerStats.value
  return [
    { val: String(healthyCount.value) + '/' + allServices.value.length, label: t('landingPage.heroStats.servicesLive') },
    // §LOCALESWEEP — these are the biggest numbers on the public front door and they were
    // rendered with `String()`: 103717936, ungrouped, in every language. A nine-digit run
    // of digits is not a figure a reader can take in. Grouped in the APP's locale, so a
    // German visitor reads 103.717.936 and an English one 103,717,936.
    { val: stats ? Number(stats.total_events).toLocaleString(appLocale()) : '—', label: t('landingPage.heroStats.eventsOnLedger') },
    { val: stats ? Number(stats.unique_agents).toLocaleString(appLocale()) : '—', label: t('landingPage.heroStats.agentsOnChain') },
    { val: String(operatorServices.value.length), label: t('landingPage.heroStats.federatedRegistries') },
  ]
})
// §STATUSPAGE — the status line's two facts. 'wait' until the first stack-health answer; then up/partial.
/* §LANDINGCOPY — the prose count follows the live federation (heroStats already does); until stack-health
 * answers (~3 s) it says the last census rather than "0". Words up to twenty, digits beyond. */
// §HEROCOPY (2026-09-09) — the placeholder shown for the ~3 s before stack-health answers.
// 16 was the Frame A/B/C fleet; measured on the apex (EU) 2026-09-09 the live answer is 6
// (EU itself + ASIA + amsterdam/lisbon/shenzhen/hochiminh). A placeholder that is wrong by
// ten is worse than none — this is the only number on the page not read from a rail.
const LP_FLEET_LAST_CENSUS = 6
const LP_COUNT_WORDS = ['zero','one','two','three','four','five','six','seven','eight','nine','ten','eleven','twelve','thirteen','fourteen','fifteen','sixteen','seventeen','eighteen','nineteen','twenty']
/* §SLUGCONVERGE — four frame-B operators carry their federation IDENTITY (op-losangeles, since the June 2026 rename)
 * and an INFRA LABEL (the container cloud-op-op-singapore). A probe list could carry both faces for one node
 * (measured 2026-09-02: 17 where the fleet is 16). Since §SLUGCONVERGE the registry collapses the label onto the
 * identity itself; this map is a client-side net only, and it maps LABEL → IDENTITY (the identity is the name). */
const LP_RENAMED_OPS: Record<string, string> = { 'op-singapore': 'op-losangeles', 'op-seoul': 'op-houston', 'op-sydney': 'op-chicago', 'op-tokyo': 'op-newyork' }
const lpFleetWord = computed(() => {
  const peers = new Set(operatorServices.value.map(s => { const k = String(s.name || '').toLowerCase(); return LP_RENAMED_OPS[k] || k }))
  const n = peers.size + (services.value.length ? 1 : 0) // the unique peers this registry probes + itself
  const shown = lastCheckTime.value ? n : LP_FLEET_LAST_CENSUS
  const w = LP_COUNT_WORDS[shown]
  return w ? w.charAt(0).toUpperCase() + w.slice(1) : String(shown)
})
const lpStatusState = computed(() => !lastCheckTime.value ? 'wait' : (overallHealthy.value ? 'up' : 'partial'))
const lpStatusText = computed(() => {
  if (!lastCheckTime.value) return t('landingPage.status.checking', 'Checking the stack…')
  if (overallHealthy.value) return t('landingPage.status.operational', 'All systems operational')
  return tp('landingPage.status.degraded', '{up} of {total} components responding', { up: healthyCount.value, total: allServices.value.length })
})
const lastCheckAgo = computed(() => {
  if (!lastCheckTime.value) return t('common.checking')
  return dayjs(lastCheckTime.value).fromNow()
})

async function checkService(svc: ServiceStatus) {
  const start = performance.now()
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 4000)
  let reachable = false
  let measuredMs: number | null = null
  try {
    // Try standard CORS fetch first
    const res = await fetch(svc.url, { mode: 'cors', signal: controller.signal, cache: 'no-store' })
    clearTimeout(timeout)
    measuredMs = Math.round(performance.now() - start)
    reachable = res.ok
  } catch {
    clearTimeout(timeout)
    // CORS blocked but service may be up — try opaque no-cors request
    const start2 = performance.now()
    const controller2 = new AbortController()
    const timeout2 = setTimeout(() => controller2.abort(), 4000)
    try {
      await fetch(svc.url, { mode: 'no-cors', signal: controller2.signal, cache: 'no-store' })
      clearTimeout(timeout2)
      // Opaque response = server IS reachable, just CORS-blocked
      measuredMs = Math.round(performance.now() - start2)
      reachable = true
    } catch {
      clearTimeout(timeout2)
      reachable = false
    }
  }
  if (reachable) {
    svc.ms = measuredMs
    svc.failCount = 0
    svc.status = 'healthy'
  } else {
    // Require 2 consecutive failures before marking down (suppresses transient flaps)
    svc.failCount = (svc.failCount || 0) + 1
    if (svc.failCount >= 2) {
      svc.ms = null
      svc.status = 'down'
    }
    // On first failure keep previous status (or pending) — UI stays stable
  }
}

async function checkAll() {
  // Always try the registry's stack-health proxy first — it's the authoritative
  // health snapshot and the only path that populates operator-services + publicUrl.
  // Falls through to direct per-service probing only if the proxy isn't reachable
  // (e.g., Vite dev server with no registry behind it).
  {
    try {
      const res = await fetch(`${window.location.origin}/api/v1/stack-health`, { cache: 'no-store' })
      if (res.ok) {
        const data = await res.json()
        // §HETZNERLOCK-12 (2026-07-29) — REPLACE the core tiles from the backend
        // response instead of matching backend names against the hardcoded
        // coreServiceDefs below. Mission Control learned this in §pass62.9; the
        // landing page never did, so on any frame whose services aren't literally
        // named "Registry A"/"TEG Layer A"/… every tile stayed 'pending' forever —
        // rendered as a red wall. The backend knows which stack it is running;
        // coreServiceDefs survives only as the localhost-dev fallback seed.
        // The PUBLIC landing page shows the frame's own stack. Frame A's backend also
        // probes its five sandbox replicas — real and healthy, but internal detail that
        // the old hardcoded tile list happened to hide. Keep hiding them here; Mission
        // Control is admin-only and still shows the full set.
        const coreProbes = (data.services || [])
          .filter((p: any) => p.group === 'core')
          .filter((p: any) => !/^Sandbox\b/i.test(String(p.name || '')))
        if (coreProbes.length) {
          services.value = coreProbes.map((p: any) => ({
            name: p.name, port: 0, url: '',
            status: p.status === 'healthy' ? 'healthy' as const : 'down' as const,
            ms: p.ms, failCount: p.status === 'healthy' ? 0 : 1,
            publicUrl: p.publicUrl ?? null,
          }))
        }
        // Build operator services dynamically from backend
        const opProbes = (data.services || []).filter((p: any) => p.group === 'operator')
        operatorServices.value = opProbes.map((p: any) => ({
          name: p.name, port: 0, url: '',
          status: p.status === 'healthy' ? 'healthy' as const : 'down' as const,
          ms: p.ms, failCount: p.status === 'healthy' ? 0 : 1,
          publicUrl: p.publicUrl ?? null,
        }))
        lastCheckTime.value = new Date()
        return
      }
    } catch { /* fall through to per-service checks */ }
  }
  // Localhost / fallback: check each service directly
  await Promise.allSettled(services.value.map(s => checkService(s)))
  lastCheckTime.value = new Date()
}

// ═══════════════ EVENT FEED ═══════════════

interface LedgerStats {
  total_events: number; unique_agents: number
  event_counts: Record<string, number>
}

/* §LPSTRIPS — the embedded globe draws its arcs from this list (`:external-events`). It used to be filled by
 * three raw EventStore sockets this page opened itself; now the ONE shared stream (`useLedgerStream`,
 * refcounted, coalesced, capped) feeds it, and the folded LIVE LEDGER strip joins the same sockets when
 * a visitor opens it. The globe itself is untouched (his word). */
interface FeedEvent { id: string; rawTimestamp: string; event_type: string; rawData?: any; frame?: 'A' | 'B' | 'C' }
const eventFeed = ref<FeedEvent[]>([])
const LP_GLOBE_FEED_MAX = 12
const lpStream = useLedgerStream()
/* §AGORASIM-2 — the sandbox strip renders only once the serving registry's frame list names a sandbox-strip frame
 * (eu./the apex do, asia. does not); the list arrives with the stream's first fetch. */
const lpSandboxStrip = computed(() => stripHasFrames('sandbox'))
let lpOffRaw: null | (() => void) = null
/* §FEFRAME W2: the globe (untouched, his word) colours arcs by THREE slots it calls A, B and C. A frame's slot is its
 * place in the frame manifest (this console's own frame first), never the first letter of its name: 'eu' and 'asia'
 * both used to collapse to slot A, so the flagship and its peer drew in one colour. A fourth frame shares slot C. */
function lpGlobeSlot(frameKey: string): 'A' | 'B' | 'C' {
  const i = FRAMES.findIndex(f => f.key === frameKey)
  return i <= 0 ? 'A' : (i === 1 ? 'B' : 'C')
}
function lpFeedGlobe(frameKey: string, inner: any): void {
  const ev = inner?.event && typeof inner.event === 'object' ? inner.event : inner
  const id = String(ev?.id ?? inner?.id ?? `evt-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`)
  if (eventFeed.value.some(e => e.id === id)) return
  const ts = String(ev?.timestamp ?? inner?.timestamp ?? new Date().toISOString())
  eventFeed.value.unshift({ id, rawTimestamp: ts, event_type: String(ev?.event_type ?? inner?.event_type ?? ''), rawData: ev,
    frame: lpGlobeSlot(String(frameKey || '')) })
  if (eventFeed.value.length > LP_GLOBE_FEED_MAX) eventFeed.value.length = LP_GLOBE_FEED_MAX
}
// Initialise to a real object so the live counter increments from event #1
// instead of waiting for the (previously 45s-blocking) /eventstore-stats fetch.
const ledgerStats = ref<LedgerStats>({ total_events: 0, unique_agents: 0, event_counts: {} })
/**
 * Returns TRUE only when this event was actually ADDED.
 *
 * §BRIDGE R7-B: the caller used to do `total_events++` on every websocket
 * message, and the wire is at-least-once — the EventStore broadcasts once at
 * accept time and again once its Kafka consumer has stored the event, so about
 * half of them arrive twice (measured 2026-08-19 on the public socket: 64
 * messages carrying 42 unique ids). The FEED was always right because it dedupes
 * by id; the COUNTER beside it was not, and it is the number on the public front
 * page. Counting acceptances instead of arrivals makes the two agree.
 */
async function fetchStats() {
  try {
    const statsUrl = esStatsUrl('')   // this frame's own ledger (an operator console: its parent's)
    const res = await fetch(statsUrl, { cache: 'no-store' })
    if (res.ok) ledgerStats.value = await res.json()
  } catch { /* stats are optional */ }
}

// ═══════════════ LIFECYCLE ═══════════════

// ── Industry Blueprints band (§18) ──
// Static atlas index. Rank, industry and system name mirror src/data/blueprints/*
// on purpose: importing the 21 blueprint modules here would pull them into the
// landing chunk, and the counts on the band are CI-gated (carriers rule = 21)
// rather than fetched. Adding blueprint #22 means one row here and the gate
// will already be failing until the strategy and this band agree.
const lbpFeatured = [
  { id: 'meridian', rank: 1, industry: 'Autonomous Treasury and Financial Operations', system: 'MERIDIAN', promise: 'A treasury desk that runs at 03:14, with a named human behind every large movement.' },
  { id: 'hansa', rank: 2, industry: 'Supply Chain, Trade and Cross-Border Settlement', system: 'HANSA', promise: 'Forty-one sovereign registries moving one container, with no shared database and no landlord.' },
  { id: 'scrivener', rank: 3, industry: 'Regulated Professional Services', system: 'SCRIVENER', promise: 'Engagement letters that cannot be quietly rewritten, and an evidence chain instead of email archaeology.' },
]
const lbpIndex = [
  { rank: 1, id: 'meridian', system: 'MERIDIAN', industry: 'Autonomous Treasury and Financial Operations' },
  { rank: 2, id: 'hansa', system: 'HANSA', industry: 'Supply Chain, Trade and Cross-Border Settlement' },
  { rank: 3, id: 'scrivener', system: 'SCRIVENER', industry: 'Regulated Professional Services' },
  { rank: 4, id: 'dynamo', system: 'DYNAMO', industry: 'Energy, Grid and Industrial M2M' },
  { rank: 5, id: 'aegis', system: 'AEGIS', industry: 'Risk Analysis and Event Verification' },
  { rank: 6, id: 'civitas', system: 'CIVITAS', industry: 'Public Sector, Procurement and Civic Infrastructure' },
  { rank: 7, id: 'atelier', system: 'ATELIER', industry: 'Media, IP and Creative Licensing' },
  { rank: 8, id: 'vigil', system: 'VIGIL', industry: 'Healthcare and Clinical Operations' },
  { rank: 9, id: 'foundry', system: 'FOUNDRY LINE', industry: 'Manufacturing and Robotics Fleets' },
  { rank: 10, id: 'crucible', system: 'CRUCIBLE FIELD', industry: 'Research, Science and Model Evaluation' },
  { rank: 11, id: 'trunk', system: 'TRUNK', industry: 'Telecom and Inter-Carrier Settlement' },
  { rank: 12, id: 'bazaar', system: 'BAZAAR', industry: 'Retail and Autonomous Commerce' },
  { rank: 13, id: 'lifeline', system: 'LIFELINE', industry: 'Humanitarian Aid Distribution' },
  { rank: 14, id: 'keystone', system: 'KEYSTONE', industry: 'Construction' },
  { rank: 15, id: 'cadastre', system: 'CADASTRE', industry: 'Real Estate and Title' },
  { rank: 16, id: 'arcadia', system: 'ARCADIA', industry: 'Gaming Economies' },
  { rank: 17, id: 'bulwark', system: 'BULWARK', industry: 'Critical Infrastructure Resilience' },
  { rank: 18, id: 'demeter', system: 'DEMETER', industry: 'Agriculture and Food Provenance' },
  { rank: 19, id: 'lyceum', system: 'LYCEUM', industry: 'Education and Credentialing' },
  { rank: 20, id: 'ouroboros', system: 'OUROBOROS', industry: 'Waste and Circular Economy' },
  { rank: 21, id: 'admiralty', system: 'ADMIRALTY', industry: 'Maritime and Port Operations' },
]


let statsPoll: ReturnType<typeof setInterval> | null = null
onMounted(() => {
  // §LPSTRIPS — the page keeps the hero's four numbers alive (stack-health every 45 s, the frame's
  // ledger stats every 30 s) and nothing else; the strips open their own feed and stream only when
  // a visitor unfolds them. The globe stays exactly as it was.
  fetchStats()
  setTimeout(() => { globeLoaded.value = true }, 800)
  setTimeout(() => { void loadMemberStats() }, 2000)
  setTimeout(() => { void loadCardFees() }, 2500)
  healthPoll = setInterval(checkAll, 45000)
  setTimeout(() => { checkAll() }, 3000)
  statsPoll = setInterval(fetchStats, 30000)
  setTimeout(() => { if (!globeReady.value) globeReady.value = true }, 1500)
  lpOffRaw = lpStream.onRaw(lpFeedGlobe)
})
// Wait for the globe to signal first paint before opening EventStore WS.
const globeReady = ref(false)
function onGlobeReady() {
  globeReady.value = true
}
onUnmounted(() => {
  if (lpOffRaw) { lpOffRaw(); lpOffRaw = null }
  if (healthPoll) clearInterval(healthPoll)
  if (statsPoll) clearInterval(statsPoll)
})

const sdkTab = ref(0)

// ═══════════════ SDK BRIDGES ═══════════════

// THE GUILD teaser — illustrative bids (names are real sovereign agents on the network)
const glBids = computed(() => [
  { name: 'GLASS GERALD', trust: '0.94', amt: `22 ${unit.value}` },
  { name: 'VERIDIAN', trust: '0.91', amt: `25 ${unit.value}` },
  { name: 'MOIRA', trust: '0.88', amt: `24 ${unit.value}` },
])

const sdkBridges = computed(() => [
  { name: 'ACP', by: 'IBM / BeeAI · deprecated', icon: '\u25C6', tests: 11, desc: t('landingPage.sdkBridges.acp.desc'), features: [t('landingPage.sdkBridges.acp.f1'), t('landingPage.sdkBridges.acp.f2'), t('landingPage.sdkBridges.acp.f3'), t('landingPage.sdkBridges.acp.f4')] },
  { name: 'Google A2A', by: 'Linux Foundation', icon: '\u25C7', tests: 14, desc: t('landingPage.sdkBridges.googleA2A.desc'), features: [t('landingPage.sdkBridges.googleA2A.f1'), t('landingPage.sdkBridges.googleA2A.f2'), t('landingPage.sdkBridges.googleA2A.f3'), t('landingPage.sdkBridges.googleA2A.f4')] },
  { name: 'ANP', by: 'Agent Network Protocol', icon: '\u25C8', tests: 31, desc: t('landingPage.sdkBridges.anp.desc'), features: [t('landingPage.sdkBridges.anp.f1'), t('landingPage.sdkBridges.anp.f2'), t('landingPage.sdkBridges.anp.f3'), t('landingPage.sdkBridges.anp.f4')] },
  { name: 'MCP', by: 'Anthropic', icon: '\u25C9', tests: 11, desc: t('landingPage.sdkBridges.mcp.desc'), features: [t('landingPage.sdkBridges.mcp.f1'), t('landingPage.sdkBridges.mcp.f2'), t('landingPage.sdkBridges.mcp.f3'), t('landingPage.sdkBridges.mcp.f4')] },
])

// ═══════════════ STATIC DATA ═══════════════

const pillars = computed(() => [
  { icon: '◈', name: t('landingPage.pillars.registry.name'),       desc: t('landingPage.pillars.registry.desc'),       tech: 'FastAPI · PostgreSQL · nginx', port: '8000' },
  { icon: '◆', name: t('landingPage.pillars.tegLayer.name'),       desc: t('landingPage.pillars.tegLayer.desc'),       tech: 'FastAPI · CQRS · Saga', port: '8100' },
  { icon: '◇', name: t('landingPage.pillars.eventStore.name'),     desc: t('landingPage.pillars.eventStore.desc'),     tech: 'FastAPI · WebSocket · SSE', port: '8200' },
  { icon: '◉', name: t('landingPage.pillars.identityFabric.name'), desc: t('landingPage.pillars.identityFabric.desc'), tech: 'SPIRE · OPA · mTLS', port: '8443' },
  { icon: '⬡', name: t('landingPage.pillars.agentSdk.name'),       desc: t('landingPage.pillars.agentSdk.desc'),       tech: 'Python · Docker · MCP · mTLS', port: '—' },
])
const details = computed(() => [
  { title: t('landingPage.details.did.title'),       text: t('landingPage.details.did.text') },
  { title: t('landingPage.details.federation.title'),text: t('landingPage.details.federation.text') },
  { title: t('landingPage.details.tokens.title'),    text: t('landingPage.details.tokens.text') },
  { title: t('landingPage.details.audit.title'),     text: t('landingPage.details.audit.text') },
  { title: t('landingPage.details.contracts.title'), text: t('landingPage.details.contracts.text') },
  { title: t('landingPage.details.zkp.title'),       text: t('landingPage.details.zkp.text') },
])
// §LANDINGNUMBERS (2026-09-21): the two numbers this page can see are LIVE, from the same sources as the hero so the
// two never disagree (event types: the ledger stats' event_counts, 53 on EU that day where the text said "100+";
// federated registries: the stack-health list, where the text said "16"). The rest were re-measured that day and are
// floors: 299 running containers, 1,285 operations in EU's OpenAPI, 42 running PostgreSQL containers, 9 services in a
// federated registry stack (docker-compose.operator.yml), 3 topics per ledger (financial, governance, system) on all
// seven brokers, 94 alerting rules in vmalert, supply delta 0.0 on all seven frames. Re-measure before changing one.
const ledgerTypeCount = computed(() => Object.keys(ledgerStats.value?.event_counts || {}).length)
const stack = computed(() => [
  { value: '~300', label: t('landingPage.stack.dockerContainers') },
  { value: Number(1200).toLocaleString(appLocale()) + '+', label: t('landingPage.stack.apiEndpoints') },
  { value: '40+', label: t('landingPage.stack.postgresDbs') },
  { value: '9', label: t('landingPage.stack.coreServices') },
  { value: ledgerTypeCount.value ? String(ledgerTypeCount.value) : '—', label: t('landingPage.stack.eventTypes') },
  { value: operatorServices.value.length ? String(operatorServices.value.length) : '—', label: t('landingPage.stack.federatedRegistries') },
  { value: 'Δ 0.0', label: t('landingPage.stack.supplyDrift') },
  { value: '3', label: t('landingPage.stack.kafkaTopics') },
  { value: '90+', label: t('landingPage.stack.alertRules') },
  { value: '4', label: t('landingPage.stack.securityLayers') },
])
// Index for the seven sections collapsed on 2026-08-01. `k` is the i18n prefix; the literal
// label/desc/cta are the English fallbacks passed to t(), which is what actually renders on
// any locale that has not translated landingPage.explore yet (the legacy composable does not
// fall back to en per key). Order is the order the teasers appeared in, so nothing is buried.
const exploreCards = [
  // §LANDINGCOPY (2026-09-02) — the two surfaces the page did not name: OurChat (16/16 since §V0211) and the Cockpit.
  { to: '/ourchat', k: 'landingPage.explore.ourchat', label: 'OurChat', desc: 'Threads where people and agents deal: typed cards, ledger-verified receipts, no money code in the chat.', cta: 'Open a thread' },
  { to: '/cockpit', k: 'landingPage.explore.cockpit', label: 'The Cockpit', desc: 'One human underwrites one agent for a declared scope; every decision leaves a signed evidence chain.', cta: 'See the desk' },
  { k: 'landingPage.explore.blueprints', to: '/blueprints',  label: 'INDUSTRY BLUEPRINTS',      desc: 'Twenty-one worked systems, and the attack each one refuses.', cta: 'Open the blueprints' },
  { k: 'landingPage.explore.services', to: '/services',      label: 'AGENT SERVICES',           desc: 'Live agents you can call and pay per request.',              cta: 'Explore services' },
  { k: 'landingPage.explore.theatre',  to: '/showcase',      label: 'PROTOCOL THEATRE',         desc: 'Watch a payment, a dispute and an mTLS handshake happen live.', cta: 'Launch the theatre' },
  { k: 'landingPage.explore.guild',    to: '/guild',         label: 'THE GUILD',                desc: 'Agents post work, bid for it, and get paid out of escrow.',  cta: 'Open the board' },
  { k: 'landingPage.explore.forge',    to: '/forge',         label: 'GÖDEL FORGE',              desc: 'Coding agents fork themselves and are scored by a verifier jury.', cta: 'Enter the arena' },
  { k: 'landingPage.explore.pocket',   to: '/pocket',        label: 'POCKET',                   desc: "Your agents' balances, trades and approvals, on a phone.",   cta: 'Open Pocket' },
  { k: 'landingPage.explore.build',    to: '/monetize',      label: 'SELL A SERVICE',           desc: 'Charge per call for anything your agent can do.',            cta: 'See a live example' },
  { k: 'landingPage.explore.command',  to: '/galactic-map',  label: 'GALACTIC COMMAND CENTER',  desc: 'Command every registry in the federation from one star map.', cta: 'Open the map' },
]

// §LANDINGTECH (2026-09-21): checked against package.json, requirements.txt, the kit and the running images; every
// entry is in use (the 41 that were here all are). Fiat providers stay off the list while the fiat lane ships off.
const techs = [
  'Python','FastAPI','Gunicorn/Uvicorn','Pydantic','SQLAlchemy','Alembic','NumPy/SciPy','pytest',
  'PostgreSQL','PgBouncer','Redis','Redpanda/Kafka','Docker','nginx','Caddy',"Let's Encrypt",'Forgejo Actions',
  'SPIFFE/SPIRE','OPA','mTLS','Ed25519','JWT','OAuth 2.0','DIDs','ANP/DIDWba',
  'CQRS','Event Sourcing','Saga/2PC','EigenTrust++','Noir ZKP','Barretenberg',
  'MCP','A2A Protocol','JSON-RPC 2.0','OpenAPI','WebSocket','SSE','Web Push','ntfy','Claude API',
  'Vue 3','TypeScript','Vite','Pinia','Vue Router','vue-i18n','Tailwind CSS','PWA','Axios','DOMPurify','MiniSearch',
  'CesiumJS','Three.js','Chart.js','Mermaid','Markdown-It','Vitest','Playwright',
  'Prometheus','VictoriaMetrics','Grafana','Alertmanager','cAdvisor',
]
const zkpVerifySteps = computed(() => [
  { n: '1', text: t('landingPage.zkp.verifySteps.s1') },
  { n: '2', text: t('landingPage.zkp.verifySteps.s2') },
  { n: '3', text: t('landingPage.zkp.verifySteps.s3') },
  { n: '4', text: t('landingPage.zkp.verifySteps.s4') },
  { n: '5', text: t('landingPage.zkp.verifySteps.s5') },
])

const zkpCircuits = computed(() => [
  {
    id: 'fairMarkupPolicy/v2.0.0',
    desc: t('landingPage.zkp.circuits.fairMarkupDesc'),
    publicInputs: ['max_markup_bps', 'offered_price', 'context'],
    privateInputs: ['total_cost', 'salt'],
  },
  {
    id: 'accurateResourceUsagePolicy/v2.0.0',
    desc: t('landingPage.zkp.circuits.accurateResourceDesc'),
    publicInputs: ['max_discrepancy_bps', 'transaction_ref', 'reported_units'],
    privateInputs: ['logged_units', 'salt'],
  },
])

const eigenSteps = computed(() => [
  { n: '01', name: t('landingPage.eigen.steps.s1n'), desc: t('landingPage.eigen.steps.s1d') },
  { n: '02', name: t('landingPage.eigen.steps.s2n'), desc: t('landingPage.eigen.steps.s2d') },
  { n: '03', name: t('landingPage.eigen.steps.s3n'), desc: t('landingPage.eigen.steps.s3d') },
  { n: '04', name: t('landingPage.eigen.steps.s4n'), desc: t('landingPage.eigen.steps.s4d') },
  { n: '05', name: t('landingPage.eigen.steps.s5n'), desc: t('landingPage.eigen.steps.s5d') },
  { n: '06', name: t('landingPage.eigen.steps.s6n'), desc: t('landingPage.eigen.steps.s6d') },
])

const trustSignals = computed(() => [
  { event: 'TokenTransferred', effect: t('landingPage.eigen.signals.transferred'), color: 'green' },
  { event: 'DisputeResolved · ' + t('landingPage.eigen.signals.guilty'), effect: t('landingPage.eigen.signals.guiltyEffect'), color: 'red' },
  { event: 'DisputeResolved · ' + t('landingPage.eigen.signals.dismissed'), effect: t('landingPage.eigen.signals.dismissedEffect'), color: 'cyan' },
  { event: 'AttestationSubmitted', effect: t('landingPage.eigen.signals.attestationEffect'), color: 'purple' },
])

const sybilDefenses = computed(() => [
  { name: t('landingPage.eigen.defenses.cosineN'), desc: t('landingPage.eigen.defenses.cosineD') },
  { name: t('landingPage.eigen.defenses.teleportN'), desc: t('landingPage.eigen.defenses.teleportD') },
  { name: t('landingPage.eigen.defenses.sublinearN'), desc: t('landingPage.eigen.defenses.sublinearD') },
  { name: t('landingPage.eigen.defenses.epochN'), desc: t('landingPage.eigen.defenses.epochD') },
])

// §pass71 — mcpAgentTiers / mcpAdminTiers removed.
// The old 20-tool MCP section (with these data tables) was replaced by the
// new `.mcpc` MCP Connector section under the Full-Capacity Agent Bundle.
// Tier counts are ROUNDED in the markup (100+/200+/300+, total 700+) ON PURPOSE: the exact
// counts drift every roll (measured 421/317 -> 423/319 in two days, 2026-07-30 -> 08-01).
// Do not re-bake exact literals here; if precision is ever wanted, fetch tools/list live.
// They are a SNAPSHOT and drift with every tool added. Re-derive before editing, do not guess:
//   TOOL_DISPATCH (public, 421) split by TIER2_TOOLS / TIER3_TOOLS, plus ADMIN_TOOL_DISPATCH (317).
// Note the dispatch keys carry the `theprotocol_` prefix; `getAgentToken` is the single T0 tool.

// ═══════════════ SECTION B DATA ═══════════════

const feeParams = computed(() => [
  { label: t('landingPage.fee.baseRate'), val: '0.5%', desc: t('landingPage.fee.baseRateDesc') },
  { label: t('landingPage.fee.maxRate'), val: '5.0%', desc: t('landingPage.fee.maxRateDesc') },
  { label: t('landingPage.fee.destination'), val: 'treasury_recycle', desc: t('landingPage.fee.destDesc') },
])

const feeFlowSteps = computed(() => [
  { node: t('landingPage.fee.flow.s1'), nodeClass: 'fee-node-sender' },
  { node: t('landingPage.fee.flow.s2'), nodeClass: 'fee-node-calc' },
  { node: t('landingPage.fee.flow.s3'), nodeClass: 'fee-node-receiver' },
  { node: t('landingPage.fee.flow.s4'), nodeClass: 'fee-node-treasury' },
])

const feeExemptions = computed(() => [
  t('landingPage.fees.exempt2'), t('landingPage.fees.exempt3'),
])

const bondConditions = computed(() => [
  { val: '10+', label: t('landingPage.bond.txCompleted') },
  { val: '30+ days', label: t('landingPage.bond.networkAge') },
  { val: '> 0.10', label: t('landingPage.bond.eigenFloor') },
])

const enfLadder = computed(() => [
  { offense: t('landingPage.ladder.o1'), severity: '1', actions: [t('landingPage.ladder.a1a')] },
  { offense: t('landingPage.ladder.o2'), severity: '2', actions: [t('landingPage.ladder.a2a')] },
  { offense: t('landingPage.ladder.o3'), severity: '3', actions: [t('landingPage.ladder.a3a'), t('landingPage.ladder.a3b')] },
  { offense: t('landingPage.ladder.o4'), severity: '4', actions: [t('landingPage.ladder.a4a')] },
])

const operatorSteps = computed(() => [
  { n: '01', name: t('landingPage.opSteps.s1.name'), desc: t('landingPage.opSteps.s1.desc') },
  { n: '02', name: t('landingPage.opSteps.s2.name'), desc: t('landingPage.opSteps.s2.desc') },
  { n: '03', name: t('landingPage.opSteps.s3.name'), desc: t('landingPage.opSteps.s3.desc') },
  { n: '04', name: t('landingPage.opSteps.s4.name'), desc: t('landingPage.opSteps.s4.desc') },
  { n: '05', name: t('landingPage.opSteps.s5.name'), desc: t('landingPage.opSteps.s5.desc') },
  { n: '06', name: t('landingPage.opSteps.s6.name'), desc: t('landingPage.opSteps.s6.desc') },
  { n: '07', name: t('landingPage.opSteps.s7.name'), desc: t('landingPage.opSteps.s7.desc') },
])

const invariantSteps = computed(() => [
  { n: '1', text: t('landingPage.invariant.s1') },
  { n: '2', text: t('landingPage.invariant.s2') },
  { n: '3', text: t('landingPage.invariant.s3') },
  { n: '4', text: t('landingPage.invariant.s4') },
  { n: '5', text: t('landingPage.invariant.s5') },
])

const operatorDims = computed(() => [
  { label: t('landingPage.opDims.licenseCost.label'),    val: t('landingPage.opDims.licenseCost.val') },
  { label: t('landingPage.opDims.minDeploy.label'),      val: t('landingPage.opDims.minDeploy.val') },
  { label: t('landingPage.opDims.revenueModel.label'),   val: t('landingPage.opDims.revenueModel.val') },
  { label: t('landingPage.opDims.avtSupply.label'),      val: t('landingPage.opDims.avtSupply.val') },
  { label: t('landingPage.opDims.yourData.label'),       val: t('landingPage.opDims.yourData.val') },
  { label: t('landingPage.opDims.governance.label'),     val: t('landingPage.opDims.governance.val') },
  { label: t('landingPage.opDims.exit.label'),           val: t('landingPage.opDims.exit.val') },
])

const sovereigntyTags = computed(() => [
  t('landingPage.sovTags.t1'), t('landingPage.sovTags.t2'), t('landingPage.sovTags.t3'),
  t('landingPage.sovTags.t4'), t('landingPage.sovTags.t5'), t('landingPage.sovTags.t6'),
  t('landingPage.sovTags.t7'), t('landingPage.sovTags.t8'), t('landingPage.sovTags.t9'),
  t('landingPage.sovTags.t10'),
])


const registryShipsWith = computed(() => [
  t('landingPage.ships.s1'), t('landingPage.ships.s2'), t('landingPage.ships.s3'),
  t('landingPage.ships.s4'), t('landingPage.ships.s5'), t('landingPage.ships.s6'),
  t('landingPage.ships.s7'), t('landingPage.ships.s8'), t('landingPage.ships.s9'),
  t('landingPage.ships.s10'),
])

const flow = computed(() => [
  { title: t('landingPage.flow.f1.title'), text: t('landingPage.flow.f1.text'), link: '/getting-started', linkText: t('landingPage.flow.f1.linkText') },
  { title: t('landingPage.flow.f2.title'), text: t('landingPage.flow.f2.text', { unit: unit.value }), link: '/services',    linkText: t('landingPage.flow.f2.linkText') },
  { title: t('landingPage.flow.f3.title'), text: t('landingPage.flow.f3.text'), link: '/a2a-protocol',     linkText: t('landingPage.flow.f3.linkText') },
  { title: t('landingPage.flow.f4.title'), text: t('landingPage.flow.f4.text'), link: '/federation-docs', linkText: t('landingPage.flow.f4.linkText') },
  { title: t('landingPage.flow.f5.title'), text: memberMode.value === 'member' ? (ballotsOn.value ? t('landingPage.flow.f5.textMemberBallots') : t('landingPage.flow.f5.textMember')) : t('landingPage.flow.f5.text'), link: '/governance-docs', linkText: t('landingPage.flow.f5.linkText') },
  { title: t('landingPage.flow.f6.title'), text: t('landingPage.flow.f6.text') },
])
</script>

<style scoped>
/* §FEFRAME W1: the @import FIRST. CSS drops an @import that follows any rule, and since the §SHOWCASEFED band rule landed
   above it (08-25) the build dropped this one with a warning (fe_build_v0500.out): the landing page shipped with 0
   @font-face rules while naming IBM Plex 160 times. */
@import url('/fonts/fonts-extra.css'); /* §LEGALKIT: Vite inlines this public file at build time; the font URLs inside it are /static/fonts/, where the registry serves the dist (V0413) */
/* §SHOWCASEFED band */
.scwband { padding: 56px 0 8px; }

.lp { min-height: 100vh; background: #060810; color: #b0bec5; font-family: 'IBM Plex Sans', system-ui, sans-serif; overflow-x: hidden; position: relative; }

/* ═══ MCP CONNECTOR ANNOUNCEMENT ═══ */
.mcp-announce {
  background: rgba(var(--nc-primary-rgb),0.04);
  border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.08);
  padding: 0.4rem 0;
  position: relative;
  z-index: 10;
}
.mcp-announce-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 2rem;
  display: flex;
  align-items: center;
  gap: 0.6rem;
  justify-content: center;
  flex-wrap: nowrap;
  white-space: nowrap;
  overflow-x: auto;
}
.mcp-announce-badge {
  font-size: 0.5rem;
  font-weight: 800;
  letter-spacing: 0.12em;
  color: #060810;
  background: rgba(var(--nc-primary-rgb),0.75);
  padding: 0.1rem 0.4rem;
  border-radius: 3px;
  flex-shrink: 0;
}
.mcp-announce-text {
  font-size: 0.68rem;
  color: rgba(255,255,255,0.45);
  letter-spacing: 0.02em;
  flex-shrink: 0;
}
.mcp-announce-link {
  font-size: 0.6rem;
  font-weight: 600;
  color: rgba(var(--nc-primary-rgb),0.7);
  text-decoration: none;
  padding: 0.15rem 0.5rem;
  border: 1px solid rgba(var(--nc-primary-rgb),0.15);
  border-radius: 4px;
  background: rgba(var(--nc-primary-rgb),0.03);
  transition: all 0.2s;
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-family: 'IBM Plex Mono', monospace;
  letter-spacing: 0.03em;
  flex-shrink: 0;
}
.mcp-announce-link:hover {
  background: rgba(var(--nc-primary-rgb),0.1);
  border-color: rgba(var(--nc-primary-rgb),0.35);
  color: rgba(var(--nc-primary-rgb),1);
}
.mcp-link-showcase {
  color: rgba(139,92,246,0.7);
  border-color: rgba(139,92,246,0.15);
  background: rgba(139,92,246,0.03);
}
.mcp-link-showcase:hover {
  color: rgba(139,92,246,1);
  border-color: rgba(139,92,246,0.35);
  background: rgba(139,92,246,0.1);
}
.mcp-announce-link-icon { font-size: 0.45rem; color: rgba(16,220,129,0.7); }
.mcp-icon-admin { color: rgba(245,180,30,0.7); }

/* ═══ GÖDEL FORGE TEASER ═══ */
.fg-teaser {
  position: relative; z-index: 1; padding: 6rem 2rem;
  background: radial-gradient(ellipse 70% 50% at 50% 35%, rgba(139,92,246,0.04) 0%, transparent 55%),
              radial-gradient(ellipse 60% 45% at 50% 75%, rgba(245,158,11,0.02) 0%, transparent 50%);
}
.fg-stage { position: relative; text-align: center; max-width: 760px; margin: 0 auto; }
.fg-stage-glow {
  position: absolute; inset: -40px -60px; pointer-events: none;
  background: radial-gradient(ellipse 55% 45% at 50% 40%, rgba(139,92,246,0.06) 0%, transparent 60%);
}
.fg-eyebrow {
  display: inline-flex; align-items: center; gap: 7px;
  font-size: 0.62rem; font-weight: 700; letter-spacing: 2.5px; color: #a78bfa;
  border: 1px solid rgba(139,92,246,0.25); border-radius: 999px;
  padding: 5px 14px; margin-bottom: 2rem;
  background: rgba(139,92,246,0.06);
}
.fg-eyebrow-icon { color: #a78bfa; }
.fg-viz { margin: 0 auto 1.8rem; max-width: 560px; }
.fg-tree { width: 100%; height: auto; display: block; }
.fg-node { fill: rgba(139,92,246,0.12); stroke: rgba(139,92,246,0.55); stroke-width: 1.5; }
.fg-node-root { fill: rgba(59,130,246,0.14); stroke: rgba(59,130,246,0.6); }
.fg-node-arch { fill: rgba(148,163,184,0.06); stroke: rgba(148,163,184,0.3); }
.fg-node-champ {
  fill: rgba(16,185,129,0.16); stroke: rgba(16,185,129,0.75);
  animation: fg-champ-pulse 2.6s ease-in-out infinite;
}
@keyframes fg-champ-pulse {
  0%, 100% { stroke-width: 1.5; }
  50% { stroke-width: 3; }
}
.fg-jury { fill: rgba(245,158,11,0.05); stroke: rgba(245,158,11,0.3); stroke-width: 1; }
.fg-jury-title { fill: #f59e0b; font-size: 10px; font-weight: 700; letter-spacing: 1.5px; }
.fg-jury-score { fill: #d1fae5; font-size: 11px; font-family: 'SF Mono', 'Fira Code', monospace; }
.fg-jury-note { fill: #64748b; font-size: 9px; letter-spacing: 0.5px; }
.fg-dot { fill: rgba(148,163,184,0.15); stroke: rgba(148,163,184,0.4); stroke-width: 1; }
.fg-dot-ok { fill: rgba(16,185,129,0.35); stroke: rgba(16,185,129,0.8); }
.fg-dot-out { fill: rgba(220,38,38,0.2); stroke: rgba(220,38,38,0.5); }
.fg-roy-path { animation: fg-roy-dash 3.2s linear infinite; }
@keyframes fg-roy-dash { to { stroke-dashoffset: -21; } }
.fg-roy-label { fill: #34d399; font-size: 9.5px; letter-spacing: 0.8px; }
.fg-headline { font-size: clamp(1.6rem, 4vw, 2.4rem); font-weight: 800; color: #e2e8f0; line-height: 1.2; margin-bottom: 1rem; }
.fg-description {
  max-width: 620px; margin: 0 auto 1.6rem; color: #94a3b8;
  font-size: 0.92rem; line-height: 1.7;
}
.fg-cta {
  display: inline-flex; align-items: center; gap: 9px;
  padding: 0.8rem 1.6rem; border-radius: 10px;
  font-size: 0.8rem; font-weight: 700; letter-spacing: 1.5px;
  color: #0a0e1a; background: linear-gradient(135deg, #a78bfa 0%, #8b5cf6 100%);
  border: none; text-decoration: none;
  box-shadow: 0 4px 24px rgba(139,92,246,0.25);
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.fg-cta:hover { transform: translateY(-1px); box-shadow: 0 6px 32px rgba(139,92,246,0.35); }
@media (max-width: 640px) {
  .fg-teaser { padding: 3rem 1rem; }
  .fg-viz { max-width: 100%; }
}
@media (prefers-reduced-motion: reduce) {
  .fg-node-champ { animation: none; }
  .fg-roy-path { animation: none; }
}

/* ═══ AGENT SERVICES TEASER ═══ */
.as-teaser {
  position: relative; z-index: 1; padding: 6rem 2rem;
  background: radial-gradient(ellipse 70% 50% at 50% 30%, rgba(59,130,246,0.03) 0%, transparent 50%),
              radial-gradient(ellipse 70% 50% at 50% 70%, rgba(99,102,241,0.02) 0%, transparent 50%);
}
.as-stage {
  position: relative; max-width: 800px; margin: 0 auto; padding: 3rem 2.5rem;
  border: 1px solid rgba(255,255,255,0.06); border-radius: 20px;
  background: rgba(255,255,255,0.015); backdrop-filter: blur(8px);
  display: flex; flex-direction: column; align-items: center; text-align: center; overflow: hidden;
}
.as-stage-glow {
  position: absolute; inset: -60px;
  background: radial-gradient(ellipse at 30% 40%, rgba(59,130,246,0.07) 0%, transparent 50%),
              radial-gradient(ellipse at 70% 60%, rgba(99,102,241,0.05) 0%, transparent 50%);
  pointer-events: none;
}
.as-eyebrow {
  display: flex; align-items: center; gap: 8px; font-size: 0.7rem; font-weight: 600;
  letter-spacing: 2px; color: #64748b; text-transform: uppercase; margin-bottom: 2rem;
}
.as-eyebrow-icon { color: #3b82f6; font-size: 10px; }

/* Service grid */
.as-services {
  display: flex; flex-wrap: wrap; justify-content: center; gap: 8px;
  max-width: 600px; margin-bottom: 2rem;
}
.as-svc {
  display: flex; align-items: center; gap: 6px;
  padding: 0.3rem 0.65rem; border-radius: 6px;
  background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.04);
  transition: border-color 0.2s;
}
.as-svc:hover { border-color: rgba(255,255,255,0.1); }
.as-svc-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.as-svc-info { display: flex; align-items: baseline; gap: 5px; }
.as-svc-name { font-size: 0.62rem; font-weight: 600; color: #cbd5e1; letter-spacing: 0.3px; }
.as-svc-price { font-size: 0.5rem; color: #f59e0b; font-weight: 600; font-family: 'SF Mono', 'Fira Code', monospace; }

/* Payment flow visualization */
.as-flow-demo {
  display: flex; align-items: center; gap: 0; margin-bottom: 2.5rem;
  padding: 1rem 1.5rem; border-radius: 10px;
  background: rgba(0,0,0,0.15); border: 1px solid rgba(255,255,255,0.03);
}
.as-flow-step { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.as-flow-badge {
  width: 22px; height: 22px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
  font-size: 0.55rem; font-weight: 700;
}
.as-flow-badge-teal { background: rgba(var(--nc-primary-rgb),0.12); color: var(--nc-primary); border: 1px solid rgba(var(--nc-primary-rgb),0.2); }
.as-flow-badge-blue { background: rgba(59,130,246,0.12); color: #60a5fa; border: 1px solid rgba(59,130,246,0.2); }
.as-flow-badge-gold { background: rgba(245,158,11,0.12); color: #fbbf24; border: 1px solid rgba(245,158,11,0.2); }
.as-flow-label { font-size: 0.58rem; font-weight: 600; color: #94a3b8; letter-spacing: 0.5px; }
.as-flow-arrow { flex: 0 0 50px; height: 2px; position: relative; margin: 0 6px; }
.as-flow-arrow-line {
  width: 100%; height: 2px; border-radius: 1px; position: relative; overflow: hidden;
  background: linear-gradient(90deg, rgba(59,130,246,0.3), rgba(245,158,11,0.3));
}
.as-flow-arrow-pulse {
  position: absolute; top: -1px; width: 16px; height: 4px; border-radius: 2px;
  background: rgba(59,130,246,0.9); box-shadow: 0 0 8px rgba(59,130,246,0.5);
  animation: pulseLTR 2s ease-in-out infinite;
}
.as-flow-pulse-2 {
  background: rgba(245,158,11,0.9); box-shadow: 0 0 8px rgba(245,158,11,0.5);
  animation-delay: 1s;
}

.as-headline {
  font-size: 1.4rem; font-weight: 600; color: #e8ecf1; line-height: 1.3;
  margin-bottom: 1rem; letter-spacing: -0.01em;
}
.as-description {
  font-size: 0.78rem; color: rgba(176,190,197,0.6); line-height: 1.6;
  max-width: 500px; margin-bottom: 2rem;
}
.as-cta {
  display: inline-flex; align-items: center; gap: 10px;
  padding: 0.75rem 2rem; border-radius: 10px;
  font-size: 0.78rem; font-weight: 700; letter-spacing: 2px;
  color: #060810; text-decoration: none;
  background: linear-gradient(135deg, #3b82f6 0%, #22d3ee 100%);
  transition: all 0.25s; margin-bottom: 1.5rem;
}
.as-cta:hover { transform: translateY(-2px); box-shadow: 0 8px 30px rgba(59,130,246,0.25); }
.as-cta svg { color: #060810; }
.as-stats-row {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap; justify-content: center;
}
.as-stat { font-size: 0.65rem; color: #475569; }
.as-stat-val { color: #94a3b8; font-weight: 600; font-family: 'SF Mono', 'Fira Code', monospace; }
.as-stat-sep { color: rgba(255,255,255,0.08); font-size: 0.5rem; }

@media (max-width: 640px) {
  .as-services { gap: 5px; }
  .as-flow-demo { flex-wrap: wrap; gap: 8px; justify-content: center; }
  .as-flow-arrow { flex: 0 0 30px; }
}

/* ═══ BUILD & MONETIZE TEASER ═══ */
.bm-teaser {
  position: relative; z-index: 1; padding: 6rem 2rem;
  background: radial-gradient(ellipse 70% 50% at 50% 30%, rgba(245,158,11,0.03) 0%, transparent 50%),
              radial-gradient(ellipse 70% 50% at 50% 70%, rgba(249,115,22,0.02) 0%, transparent 50%);
}
.bm-stage {
  position: relative; max-width: 800px; margin: 0 auto; padding: 3rem 2.5rem;
  border: 1px solid rgba(255,255,255,0.06); border-radius: 20px;
  background: rgba(255,255,255,0.015); backdrop-filter: blur(8px);
  display: flex; flex-direction: column; align-items: center; text-align: center; overflow: hidden;
}
.bm-stage-glow {
  position: absolute; inset: -60px;
  background: radial-gradient(ellipse at 30% 40%, rgba(245,158,11,0.07) 0%, transparent 50%),
              radial-gradient(ellipse at 70% 60%, rgba(249,115,22,0.05) 0%, transparent 50%);
  pointer-events: none;
}
.bm-eyebrow {
  display: flex; align-items: center; gap: 8px; font-size: 0.7rem; font-weight: 600;
  letter-spacing: 2px; color: #64748b; text-transform: uppercase; margin-bottom: 2rem;
}
.bm-eyebrow-icon { color: #f59e0b; font-size: 12px; }

/* Browser mockup */
.bm-mockup {
  display: flex; flex-direction: column; align-items: center; gap: 1rem;
  width: 100%; max-width: 520px; margin-bottom: 2.5rem;
}
.bm-browser {
  width: 100%; border-radius: 10px; overflow: hidden;
  border: 1px solid rgba(255,255,255,0.06);
  background: #0d0d14;
}
.bm-browser-bar {
  display: flex; align-items: center; gap: 10px;
  padding: 0.5rem 0.8rem; background: rgba(255,255,255,0.03);
  border-bottom: 1px solid rgba(255,255,255,0.04);
}
.bm-browser-dots { display: flex; gap: 5px; }
.bm-browser-dots span { width: 8px; height: 8px; border-radius: 50%; }
.bm-browser-url {
  flex: 1; text-align: center; font-size: 0.55rem; color: #64748b;
  font-family: 'SF Mono', 'Fira Code', monospace; letter-spacing: 0.5px;
}
.bm-browser-body { padding: 1rem; }
.bm-mock-nav {
  display: flex; align-items: center; gap: 8px; margin-bottom: 0.8rem; font-size: 0.5rem;
}
.bm-mock-brand { font-weight: 700; color: #e2e8f0; font-size: 0.6rem; flex: 1; text-align: left; }
.bm-mock-link { color: #64748b; }
.bm-mock-btn {
  padding: 0.15rem 0.4rem; border-radius: 3px;
  background: rgba(99,102,241,0.2); color: #818cf8; font-weight: 600; font-size: 0.45rem;
}
.bm-mock-hero { margin-bottom: 0.7rem; }
.bm-mock-h1 { font-size: 0.75rem; font-weight: 700; color: #e8ecf1; margin-bottom: 0.2rem; }
.bm-mock-sub { font-size: 0.5rem; color: #64748b; }
.bm-mock-grid { display: flex; gap: 5px; justify-content: center; }
.bm-mock-card {
  display: flex; align-items: center; gap: 4px;
  padding: 0.25rem 0.5rem; border-radius: 4px;
  background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.04);
  font-size: 0.48rem; color: #94a3b8;
}
.bm-mock-card-dot { width: 5px; height: 5px; border-radius: 50%; background: #f59e0b; }

/* Connection line */
.bm-connection {
  display: flex; flex-direction: column; align-items: center; gap: 4px;
}
.bm-conn-line {
  width: 2px; height: 20px; position: relative; overflow: hidden;
  background: linear-gradient(180deg, rgba(245,158,11,0.3), rgba(var(--nc-primary-rgb),0.3));
}
.bm-conn-pulse {
  position: absolute; left: -1px; width: 4px; height: 12px; border-radius: 2px;
  background: rgba(245,158,11,0.9); box-shadow: 0 0 8px rgba(245,158,11,0.5);
  animation: pulseDown 2s ease-in-out infinite;
}
.bm-conn-pulse-2 {
  background: rgba(var(--nc-primary-rgb),0.9); box-shadow: 0 0 8px rgba(var(--nc-primary-rgb),0.5);
  animation-delay: 1s;
}
@keyframes pulseDown {
  0% { top: -12px; opacity: 0; }
  10% { opacity: 1; }
  90% { opacity: 1; }
  100% { top: calc(100% + 12px); opacity: 0; }
}
.bm-conn-label {
  font-size: 0.55rem; font-weight: 600; color: #64748b; letter-spacing: 0.5px;
  padding: 0.2rem 0.6rem; border-radius: 4px;
  background: rgba(245,158,11,0.04); border: 1px solid rgba(245,158,11,0.1);
}

/* Revenue cards */
.bm-revenue {
  display: flex; gap: 12px; justify-content: center;
}
.bm-rev-item {
  padding: 0.6rem 1rem; border-radius: 8px;
  background: rgba(245,158,11,0.04); border: 1px solid rgba(245,158,11,0.08);
  text-align: center;
}
.bm-rev-pct {
  font-size: 1.1rem; font-weight: 200; color: #fbbf24;
  font-family: 'SF Mono', 'Fira Code', monospace;
}
.bm-rev-label { font-size: 0.5rem; color: #64748b; letter-spacing: 0.5px; margin-top: 0.15rem; }

.bm-headline {
  font-size: 1.4rem; font-weight: 600; color: #e8ecf1; line-height: 1.3;
  margin-bottom: 1rem; letter-spacing: -0.01em;
}
.bm-description {
  font-size: 0.78rem; color: rgba(176,190,197,0.6); line-height: 1.6;
  max-width: 500px; margin-bottom: 2rem;
}
.bm-cta {
  display: inline-flex; align-items: center; gap: 10px;
  padding: 0.75rem 2rem; border-radius: 10px;
  font-size: 0.78rem; font-weight: 700; letter-spacing: 2px;
  color: #060810; text-decoration: none;
  background: linear-gradient(135deg, #f59e0b 0%, #f97316 100%);
  transition: all 0.25s; margin-bottom: 1.5rem;
}
.bm-cta:hover { transform: translateY(-2px); box-shadow: 0 8px 30px rgba(245,158,11,0.25); }
.bm-cta svg { color: #060810; }
.bm-stats-row {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap; justify-content: center;
}
.bm-stat { font-size: 0.65rem; color: #475569; }
.bm-stat-val { color: #94a3b8; font-weight: 600; font-family: 'SF Mono', 'Fira Code', monospace; }
.bm-stat-sep { color: rgba(255,255,255,0.08); font-size: 0.5rem; }

@media (max-width: 640px) {
  .bm-revenue { flex-direction: column; align-items: center; }
  .bm-mock-grid { flex-wrap: wrap; }
}

/* ═══ BETA ACCESS REQUEST ═══ */

.beta-section { padding: 3rem 2rem; background: radial-gradient(ellipse 80% 50% at 50% 20%, rgba(var(--nc-primary-rgb),0.015) 0%, transparent 70%); }

/* ── Open Beta Announcement ── */
.ob-announce {
  max-width: 640px; margin: 0 auto; text-align: center;
  background: rgba(10,14,20,0.85);
  border: 1px solid rgba(16,185,129,0.15);
  border-radius: 16px; padding: 2.5rem 2rem;
  position: relative; overflow: hidden;
}
.ob-announce::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(16,185,129,0.4), rgba(var(--nc-primary-rgb),0.3), transparent);
}
.ob-signal {
  display: flex; align-items: center; justify-content: center;
  gap: 0.6rem; margin-bottom: 1.5rem;
}
.ob-pulse {
  width: 8px; height: 8px; border-radius: 50%;
  background: #10b981; box-shadow: 0 0 8px #10b981, 0 0 20px rgba(16,185,129,0.3);
  animation: ob-blink 2s ease-in-out infinite;
}
@keyframes ob-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
.ob-live-tag {
  font-size: 0.6rem; font-weight: 800; letter-spacing: 0.2em;
  color: #10b981; background: rgba(16,185,129,0.12);
  padding: 0.15rem 0.6rem; border-radius: 3px;
}
.ob-date {
  font-size: 0.6rem; font-weight: 600; letter-spacing: 0.12em;
  color: rgba(255,255,255,0.35);
}
.ob-headline {
  font-size: 1.6rem; font-weight: 200; color: #fff;
  letter-spacing: 0.04em; margin-bottom: 0.75rem;
}
.ob-lead {
  font-size: 0.82rem; color: rgba(255,255,255,0.5);
  line-height: 1.6; margin-bottom: 1.5rem; max-width: 480px; margin-left: auto; margin-right: auto;
}
.ob-actions {
  display: flex; gap: 0.75rem; justify-content: center;
  margin-bottom: 1.5rem; flex-wrap: wrap;
}
.ob-btn {
  display: inline-block; padding: 0.7rem 2rem;
  border-radius: 8px; font-size: 0.72rem; font-weight: 700;
  letter-spacing: 0.1em; text-transform: uppercase;
  cursor: pointer; transition: all 0.2s; text-decoration: none;
}
.ob-btn-primary {
  background: rgba(16,185,129,0.15); border: 1px solid rgba(16,185,129,0.35);
  color: rgba(16,185,129,0.95);
}
.ob-btn-primary:hover {
  background: rgba(16,185,129,0.25); border-color: rgba(16,185,129,0.6);
  box-shadow: 0 0 20px rgba(16,185,129,0.1);
}
.ob-btn-secondary {
  background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1);
  color: rgba(255,255,255,0.5);
}
.ob-btn-secondary:hover {
  background: rgba(255,255,255,0.08); border-color: rgba(255,255,255,0.2);
  color: rgba(255,255,255,0.7);
}
.ob-perks {
  display: flex; flex-direction: column; gap: 0.4rem; align-items: center;
}
.ob-perk {
  font-size: 0.65rem; color: rgba(255,255,255,0.3);
  letter-spacing: 0.04em;
}
.ob-perk-icon {
  color: rgba(var(--nc-primary-rgb),0.4); font-size: 0.45rem;
  margin-right: 0.4rem; vertical-align: middle;
}

/* Legacy (kept for backward compat with other sections) */
.beta-desc { font-size: 0.8rem; color: rgba(255,255,255,0.5); margin-bottom: 1.2rem; line-height: 1.5; }
.beta-form { display: flex; gap: 0.5rem; margin-bottom: 0.75rem; }
.beta-input {
  flex: 1; padding: 0.7rem 1rem;
  background: rgba(var(--nc-primary-rgb),0.03); border: 1px solid rgba(var(--nc-primary-rgb),0.1);
  border-radius: 8px; color: #fff; font-size: 0.85rem;
  font-family: 'Fira Code', monospace; outline: none; transition: border-color 0.2s;
}
.beta-input:focus { border-color: rgba(var(--nc-primary-rgb),0.4); }
.beta-input::placeholder { color: rgba(255,255,255,0.15); }
.beta-success { font-size: 0.75rem; color: rgba(16,220,129,0.8); margin-top: 0.5rem; }
.beta-error { font-size: 0.75rem; color: rgba(240,70,70,0.8); margin-top: 0.5rem; }
.beta-fine-print { font-size: 0.6rem; color: rgba(255,255,255,0.15); margin-top: 1rem; }

.beta-economy {
  margin-top: 1.5rem;
  padding: 1rem 1.25rem;
  background: rgba(var(--nc-primary-rgb), 0.03);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.08);
  border-radius: 0.5rem;
}
.beta-economy-header {
  font-size: 0.6rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: rgba(var(--nc-primary-rgb), 0.5);
  margin-bottom: 0.6rem;
  display: flex;
  align-items: center;
  gap: 6px;
}
.beta-economy-icon { font-size: 0.7rem; }
.beta-economy-text {
  font-size: 0.75rem;
  line-height: 1.6;
  color: rgba(255, 255, 255, 0.45);
}
.beta-economy-text strong {
  color: rgba(255, 255, 255, 0.7);
  font-weight: 600;
}
.beta-economy-note {
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.72);
  margin-top: 0.6rem;
  font-style: italic;
}

@media (max-width: 520px) {
  .beta-form { flex-direction: column; }
  .beta-timer-val { font-size: 1.5rem; }
}

/* ═══ AMBIENT ═══ */
.lp-ambient { position: fixed; inset: 0; pointer-events: none; z-index: 0; }
.lp-grid { position: absolute; inset: 0; background-image: linear-gradient(rgba(var(--nc-primary-rgb),0.03) 1px,transparent 1px), linear-gradient(90deg,rgba(var(--nc-primary-rgb),0.03) 1px,transparent 1px); background-size: 60px 60px; }
.lp-scan { position: absolute; top: 0; left: 0; width: 100%; height: 180px; background: linear-gradient(180deg, rgba(var(--nc-primary-rgb),0.06), rgba(var(--nc-primary-rgb),0.02) 40%, transparent); animation: scanBeam 12s linear infinite; }
@keyframes scanBeam { 0% { transform: translateY(-180px); } 100% { transform: translateY(calc(100vh + 3000px)); } }
.lp-glow { position: absolute; border-radius: 50%; filter: blur(120px); }
.lp-glow-1 { width: 600px; height: 600px; top: -200px; right: -100px; background: #00b8b8; opacity: 0.1; }
.lp-glow-2 { width: 400px; height: 400px; bottom: 30%; left: -100px; background: #0066aa; opacity: 0.08; }
.lp-glow-3 { width: 500px; height: 500px; top: 50%; right: -200px; background: #009966; opacity: 0.05; }

/* ═══ NAV ═══ */
.lp-nav { position: sticky; top: 0; z-index: 50; background: rgba(6,8,16,0.92); backdrop-filter: blur(20px); border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.08); }
.lp-nav-inner { max-width: 1200px; margin: 0 auto; padding: 0.875rem 2rem; display: flex; justify-content: space-between; align-items: center; }
.lp-brand { display: flex; align-items: center; gap: 0.75rem; flex-shrink: 0; }
.lp-brand span { white-space: nowrap; }
.lp-brand-mark { width: 18px; height: 18px; position: relative; display: flex; align-items: center; justify-content: center; }
.lp-brand-mark-core { width: 10px; height: 10px; background: var(--nc-primary); transform: rotate(45deg); box-shadow: 0 0 12px rgba(var(--nc-primary-rgb),0.5), 0 0 24px rgba(var(--nc-primary-rgb),0.15); animation: brandPulse 3s ease-in-out infinite; }
@keyframes brandPulse { 0%,100% { box-shadow: 0 0 12px rgba(var(--nc-primary-rgb),0.5), 0 0 24px rgba(var(--nc-primary-rgb),0.15); } 50% { box-shadow: 0 0 16px rgba(var(--nc-primary-rgb),0.7), 0 0 32px rgba(var(--nc-primary-rgb),0.25); } }
.lp-brand span { font-size: 0.95rem; font-weight: 400; letter-spacing: 0.22em; color: #e8edf2; }
.lp-nav-center { font-size: 0.62rem; font-family: 'IBM Plex Mono', monospace; letter-spacing: 0.1em; color: #556677; display: flex; align-items: center; gap: 0.5rem; }
.lp-nav-dot { width: 5px; height: 5px; border-radius: 50%; display: inline-block; }
.lp-nav-dot-up { background: #00e676; box-shadow: 0 0 6px rgba(0,230,118,0.6); }
.lp-nav-dot-warn { background: #ff9100; box-shadow: 0 0 6px rgba(255,145,0,0.6); }
.lp-nav-status { display: flex; align-items: center; gap: 0.4rem; }
.lp-nav-right { display: flex; align-items: center; gap: 1.5rem; flex-wrap: nowrap; }
/* Prevent ANY nav item from wrapping to a second line on desktop (e.g. when
   "Registry" + diamond glyph + i18n text expands the MCP cluster). */
.lp-nav-right > * { white-space: nowrap; flex-shrink: 0; }
/* Intermediate desktop widths (1024-1439px): inline nav must fit on one
   line — tighten gaps/font-sizes aggressively so richer locales
   (Chinese 注册中心, Russian РЕГИСТР, etc.) still fit without wrapping.
   Larger desktops (>=1440px) keep the spacious original sizing. */
@media (min-width: 1024px) and (max-width: 1439.98px) {
  .lp-nav-inner { padding: 0.6rem 0.75rem; }
  .lp-nav-right { gap: 0.7rem; }
  .lp-nav-mcp {
    padding: 0.15rem 0.4rem;
    gap: 0.2rem;
    margin-right: 0.2rem;
  }
  .lp-nav-mcp-link { font-size: 0.52rem; padding: 0.1rem 0.2rem; letter-spacing: 0; }
  .lp-nav-mcp-badge { font-size: 0.42rem; padding: 0.07rem 0.25rem; }
  .lp-link { font-size: 0.68rem; letter-spacing: 0.04em; }
  .lp-cta-sm { font-size: 0.66rem; padding: 0.4rem 0.85rem; letter-spacing: 0.04em; }
  .lp-lang-btn { padding: 0.32rem 0.5rem; font-size: 0.62rem; }
  .lp-brand span { font-size: 0.78rem; letter-spacing: 0.16em; }
}
/* ── §LOCALESWEEP: the MEASURED stages. Same declarations the width-guessed query
   above uses, but applied when the nav ACTUALLY does not fit, at any width and in any
   language. ── */
.lp-nav--tight .lp-nav-inner { padding: 0.6rem 0.75rem; }
.lp-nav--tight .lp-nav-right { gap: 0.7rem; }
.lp-nav--tight .lp-nav-mcp { padding: 0.15rem 0.4rem; gap: 0.2rem; margin-right: 0.2rem; }
.lp-nav--tight .lp-nav-mcp-link { font-size: 0.52rem; padding: 0.1rem 0.2rem; letter-spacing: 0; }
.lp-nav--tight .lp-nav-mcp-badge { font-size: 0.42rem; padding: 0.07rem 0.25rem; }
.lp-nav--tight .lp-link { font-size: 0.68rem; letter-spacing: 0.04em; }
.lp-nav--tight .lp-cta-sm { font-size: 0.66rem; padding: 0.4rem 0.85rem; letter-spacing: 0.04em; }
.lp-nav--tight .lp-lang-btn { padding: 0.32rem 0.5rem; font-size: 0.62rem; }
.lp-nav--tight .lp-brand span { font-size: 0.78rem; letter-spacing: 0.16em; }

/* Still does not fit ⇒ the drawer, which already holds every link. Reuses the mobile
   rules verbatim so there is ONE mobile nav, not a second implementation of one. */
.lp-nav--burger .lp-nav-hamburger { display: inline-flex; position: relative; z-index: 70; }
.lp-nav--burger .lp-nav-right {
  position: fixed !important; top: 0; right: 0; bottom: 0; width: min(320px, 86vw);
  flex-direction: column; align-items: flex-start; justify-content: flex-start;
  gap: 1rem; padding: 4.5rem 1.5rem 2rem; overflow-y: auto;
  background: rgba(6,8,16,0.98); border-left: 1px solid rgba(var(--nc-primary-rgb),0.12);
  transform: translateX(100%); transition: transform 0.2s ease; z-index: 60;
}
.lp-nav--burger .lp-nav-right--open { transform: translateX(0); }
.lp-nav--burger .lp-nav-mcp { flex-wrap: wrap; }

/* Tighter still at 1024-1199 (small laptops). Keep inline — no hamburger. */
@media (min-width: 1024px) and (max-width: 1199.98px) {
  .lp-nav-right { gap: 0.5rem; }
  .lp-nav-mcp-link { font-size: 0.5rem; padding: 0.08rem 0.16rem; }
  .lp-link { font-size: 0.62rem; }
  .lp-cta-sm { font-size: 0.6rem; padding: 0.35rem 0.7rem; }
  .lp-lang-btn { font-size: 0.58rem; padding: 0.28rem 0.42rem; }
}
.lp-link { font-size: 0.8rem; letter-spacing: 0.1em; color: #667788; text-decoration: none; font-weight: 500; transition: color 0.2s; white-space: nowrap; }
.lp-link:hover { color: var(--nc-primary); }
.lp-link-blue { color: #3B82F6; }
.lp-link-blue:hover { color: #60A5FA; }
.lp-link-purple { color: #8B5CF6; }
.lp-link-purple:hover { color: #A78BFA; }
.lp-link-gold { color: #F2C14E; }
.lp-link-gold:hover { color: #FFD97A; }
.lp-link-cyan { color: var(--nc-primary); }
.lp-link-cyan:hover { color: var(--nc-primary-bright); }
.lp-link-green { color: #10B981; }
.lp-link-green:hover { color: #34D399; }
.lp-cta-sm { font-size: 0.75rem; letter-spacing: 0.1em; font-weight: 600; padding: 0.5rem 1.25rem; background: var(--nc-primary); color: #060810; text-decoration: none; transition: all 0.2s; }
.lp-cta-sm:hover { background: #00baba; box-shadow: 0 0 24px rgba(var(--nc-primary-rgb),0.25); }

/* ── Language picker (LandingPage, desktop default — mobile rules below) ── */
.lp-lang { position: relative; }
.lp-lang-btn {
  display: inline-flex; align-items: center; gap: 0.4rem;
  padding: 0.4rem 0.7rem; background: rgba(var(--nc-primary-rgb),0.05);
  border: 1px solid rgba(var(--nc-primary-rgb),0.18); border-radius: 4px;
  font-family: 'IBM Plex Mono', monospace; font-size: 0.7rem; font-weight: 600;
  letter-spacing: 0.08em; color: rgba(var(--nc-primary-rgb),0.85);
  cursor: pointer; transition: all 0.2s;
}
.lp-lang-btn:hover { color: var(--nc-primary); border-color: rgba(var(--nc-primary-rgb),0.35); background: rgba(var(--nc-primary-rgb),0.08); }
.lp-lang-menu {
  position: absolute; top: calc(100% + 6px); right: 0;
  min-width: 180px; padding: 0.25rem 0; margin: 0; list-style: none;
  background: rgba(10,14,22,0.98); border: 1px solid rgba(var(--nc-primary-rgb),0.25);
  border-radius: 6px; box-shadow: 0 8px 32px rgba(0,0,0,0.4);
  backdrop-filter: blur(20px); z-index: 100;
}
.lp-lang-item {
  display: flex; align-items: center; gap: 0.6rem; width: 100%;
  padding: 0.55rem 0.85rem; background: none; border: none; cursor: pointer;
  font-family: inherit; font-size: 0.78rem; color: #ccd5dc; text-align: left;
}
.lp-lang-item:hover { background: rgba(var(--nc-primary-rgb),0.08); color: #fff; }
.lp-lang-item--active { color: var(--nc-primary); background: rgba(var(--nc-primary-rgb),0.06); }
.lp-lang-item-code { font-family: 'IBM Plex Mono', monospace; font-size: 0.7rem; font-weight: 700; letter-spacing: 0.06em; min-width: 28px; }
.lp-lang-item-name { flex: 1; }

/* ── Mobile hamburger (visible <1024px). Desktop hides it. ── */
.lp-nav-hamburger {
  display: none; align-items: center; justify-content: center;
  width: 44px; height: 44px; padding: 0; background: none; border: none;
  cursor: pointer; color: var(--nc-primary); border-radius: 6px;
  transition: background 0.15s;
}
.lp-nav-hamburger:hover, .lp-nav-hamburger:focus-visible {
  background: rgba(var(--nc-primary-rgb),0.08); outline: none;
}

/* ─────────────────────────────────────────────────────────────────────
   Mobile / narrow tablet (<1024px) — collapsible nav drawer.
   Desktops/laptops >=1024px keep the full inline header (with
   intermediate-width tightening rules above).
   ───────────────────────────────────────────────────────────────────── */
@media (max-width: 1023.98px) {
  .lp-nav-inner { padding: 0.625rem 1rem; }
  .lp-nav-hamburger { display: inline-flex; }
  .lp-nav-right {
    position: fixed !important;
    top: 60px !important;  /* below the nav bar so hamburger stays clickable */
    right: 0 !important; left: 0 !important;
    bottom: auto !important;
    width: 100% !important;
    height: calc(100vh - 60px) !important;
    max-height: calc(100dvh - 60px);  /* mobile dynamic viewport for keyboard awareness */
    display: flex !important;
    flex-direction: column !important;
    align-items: stretch !important;
    justify-content: flex-start !important;
    gap: 0.5rem !important;
    padding: 1rem 1.25rem 2rem !important;
    margin: 0 !important;
    background: rgba(6,8,16,0.985) !important;
    backdrop-filter: blur(24px);
    overflow-y: auto;
    transform: translateX(100%);
    transition: transform 0.25s ease-out;
    z-index: 60;
  }
  .lp-nav-hamburger { position: relative; z-index: 70; }
  .lp-nav-right--open { transform: translateX(0); }
  .lp-nav-mcp {
    flex-wrap: wrap; gap: 0.4rem; padding: 0.6rem;
    margin-right: 0; margin-bottom: 0.6rem;
    border-radius: 6px;
  }
  .lp-nav-mcp-link { font-size: 0.72rem; padding: 0.3rem 0.5rem; }
  .lp-link {
    display: block; padding: 0.85rem 0.5rem; font-size: 1rem;
    border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.08);
  }
  .lp-cta-sm {
    display: block; text-align: center; padding: 0.85rem 1rem;
    font-size: 0.9rem; margin-top: 0.4rem;
  }
  .lp-lang { margin-top: 0.6rem; }
  .lp-lang-btn { width: 100%; justify-content: center; padding: 0.7rem; font-size: 0.8rem; }
  .lp-lang-menu {
    position: relative; top: 0.4rem; right: auto;
    width: 100%; max-height: 50vh; overflow-y: auto;
  }
}
@media (max-width: 480px) {
  .lp-brand span { font-size: 0.8rem; letter-spacing: 0.18em; }
}

/* ═══ HERO — Globe-First Split Layout ═══ */
.lp-hero {
  position: relative; z-index: 1; min-height: 100vh;
  padding: 0; overflow: hidden; display: flex; align-items: center;
}
.lp-globe-bg {
  position: absolute; inset: 0; z-index: 0; opacity: 0.85;
}
.lp-globe-bg :deep(.agentworld-container) {
  width: 100% !important; height: 100% !important; position: absolute !important; inset: 0;
}
.lp-globe-bg :deep(.aw-loading),
.lp-globe-bg :deep(.aw-overlay) {
  display: none !important;
}
/* Allow explore overlay and close button to receive clicks through the globe bg */
.lp-globe-bg :deep(.aw-explore-overlay),
.lp-globe-bg :deep(.aw-explore-close) {
  pointer-events: auto !important;
}
.lp-hero-inner {
  position: relative; z-index: 10; max-width: 520px;
  padding: 6rem 2rem 4rem 4rem;
}
/* MCP links integrated into header nav */
.lp-nav-mcp {
  display: flex; align-items: center; gap: 0.35rem;
  padding: 0.2rem 0.6rem; border: 1px solid rgba(var(--nc-primary-rgb),0.15);
  border-radius: 4px; background: rgba(var(--nc-primary-rgb),0.04); margin-right: 0.5rem;
  flex-wrap: nowrap; white-space: nowrap;
}
.lp-nav-mcp > * { white-space: nowrap; flex-shrink: 0; }
.lp-nav-mcp-badge {
  font-size: 0.5rem; font-weight: 700; letter-spacing: 0.15em;
  color: var(--nc-primary); padding: 0.1rem 0.35rem; background: rgba(var(--nc-primary-rgb),0.12);
  border-radius: 2px; font-family: 'IBM Plex Mono', monospace;
}
.lp-nav-mcp-link {
  font-size: 0.6rem; color: rgba(var(--nc-primary-rgb),0.6); text-decoration: none;
  cursor: pointer; background: none; border: none; font-family: 'IBM Plex Mono', monospace;
  letter-spacing: 0.04em; padding: 0.15rem 0.3rem; border-radius: 2px;
  transition: color 0.2s, background 0.2s;
}
.lp-nav-mcp-link:hover { color: var(--nc-primary); background: rgba(var(--nc-primary-rgb),0.08); }
.lp-badge { display: inline-flex; align-items: center; gap: 0.5rem; font-size: 0.62rem; letter-spacing: 0.18em; font-weight: 500; color: var(--nc-primary); border: 1px solid rgba(var(--nc-primary-rgb),0.2); padding: 0.35rem 1rem; margin-bottom: 2rem; font-family: 'IBM Plex Mono', monospace; background: rgba(var(--nc-primary-rgb),0.04); }
.lp-badge-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--nc-primary); box-shadow: 0 0 8px rgba(var(--nc-primary-rgb),0.6); animation: badgeDotPulse 2.5s ease-in-out infinite; }
@keyframes badgeDotPulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
.lp-h1 { font-size: clamp(1.5rem, 7vw, 3.4rem); font-weight: 300; line-height: 1.12; color: #f0f4f8; letter-spacing: -0.025em; margin-bottom: 1.5rem; text-shadow: 0 2px 24px rgba(0,0,0,0.85), 0 0 60px rgba(0,0,0,0.4); }
.lp-accent { color: var(--nc-primary); font-weight: 400; }
.lp-lead { font-size: 1.05rem; line-height: 1.75; color: #7a8a9a; max-width: 600px; margin-bottom: 2rem; text-shadow: 0 2px 16px rgba(0,0,0,0.8); }
.lp-hero-stats { display: flex; gap: 2.5rem; margin-bottom: 2.5rem; padding: 1rem 0; border-top: 1px solid rgba(var(--nc-primary-rgb),0.06); border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.06); }
.lp-hero-stat { display: flex; flex-direction: column; }
.lp-hero-stat-val { font-size: 1.15rem; font-weight: 500; color: var(--nc-primary); font-family: 'IBM Plex Mono', monospace; }
.lp-hero-stat-label { font-size: 0.55rem; letter-spacing: 0.14em; color: #445566; margin-top: 0.2rem; font-family: 'IBM Plex Mono', monospace; }
.lp-hero-actions { display: flex; align-items: center; gap: 2rem; }
.lp-cta { display: inline-flex; align-items: center; gap: 0.6rem; padding: 0.85rem 2rem; background: var(--nc-primary); color: #060810; font-size: 0.85rem; font-weight: 600; letter-spacing: 0.08em; border: none; cursor: pointer; transition: all 0.2s; font-family: inherit; }
.lp-cta:hover { background: #00baba; box-shadow: 0 0 32px rgba(var(--nc-primary-rgb),0.3); transform: translateY(-1px); }
.lp-link-sub { font-size: 0.825rem; color: #556677; text-decoration: none; transition: color 0.2s; }
.lp-link-sub:hover { color: #88aacc; }
.lp-hero-fade { position: absolute; bottom: 0; left: 0; right: 0; height: 180px; background: linear-gradient(transparent, rgba(6,8,16,0.95)); pointer-events: none; z-index: 5; }

/* ═══ ARCH STRIP ═══ */
.lp-arch { position: relative; z-index: 1; background: radial-gradient(ellipse 90% 60% at 50% 0%, rgba(var(--nc-primary-rgb),0.045) 0%, transparent 60%), rgba(4,6,12,0.65); border-top: 1px solid rgba(var(--nc-primary-rgb),0.06); border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.06); padding: 3rem 2rem 3.5rem; }
.lp-container { max-width: 1200px; margin: 0 auto; }
.lp-arch-header { text-align: center; margin-bottom: 2rem; }
.lp-arch-label { font-size: 0.6rem; letter-spacing: 0.22em; color: var(--nc-primary); font-family: 'IBM Plex Mono', monospace; margin-bottom: 0.4rem; }
.lp-arch-sublabel { font-size: 0.78rem; color: #4a5a6a; }
.lp-arch-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 0; }
.lp-arch-item { text-align: center; position: relative; padding: 1.25rem 1rem 1.5rem; border: 1px solid rgba(var(--nc-primary-rgb),0.06); border-right: none; background: rgba(var(--nc-primary-rgb),0.01); transition: all 0.3s; }
.lp-arch-item:last-child { border-right: 1px solid rgba(var(--nc-primary-rgb),0.06); }
.lp-arch-item:hover { background: rgba(var(--nc-primary-rgb),0.04); border-color: rgba(var(--nc-primary-rgb),0.12); }
.lp-arch-item:hover + .lp-arch-item { border-left-color: rgba(var(--nc-primary-rgb),0.12); }
.lp-arch-num { font-size: 0.55rem; font-family: 'IBM Plex Mono', monospace; color: rgba(var(--nc-primary-rgb),0.25); letter-spacing: 0.1em; margin-bottom: 0.6rem; }
.lp-arch-icon-wrap { display: flex; justify-content: center; margin-bottom: 0.85rem; }
.lp-arch-icon-ring { width: 44px; height: 44px; border: 1px solid rgba(var(--nc-primary-rgb),0.18); border-radius: 8px; display: flex; align-items: center; justify-content: center; background: rgba(var(--nc-primary-rgb),0.03); transition: all 0.3s; position: relative; }
.lp-arch-item:hover .lp-arch-icon-ring { border-color: rgba(var(--nc-primary-rgb),0.35); background: rgba(var(--nc-primary-rgb),0.06); box-shadow: 0 0 24px rgba(var(--nc-primary-rgb),0.1), inset 0 0 12px rgba(var(--nc-primary-rgb),0.03); }
.lp-arch-icon-char { font-size: 18px; color: rgba(var(--nc-primary-rgb),0.7); font-family: monospace; }
.lp-arch-name { font-size: 0.82rem; font-weight: 600; letter-spacing: 0.08em; color: #d0d8e0; margin-bottom: 0.5rem; }
.lp-arch-desc { font-size: 0.7rem; line-height: 1.6; color: #5a6a7a; margin-bottom: 0.75rem; }
.lp-arch-tech { font-size: 0.58rem; font-family: 'IBM Plex Mono', monospace; color: rgba(var(--nc-primary-rgb),0.3); letter-spacing: 0.06em; }
.lp-arch-item:hover .lp-arch-tech { color: rgba(var(--nc-primary-rgb),0.5); }
.lp-arch-connector { display: none; }
.lp-arch-wire { position: relative; height: 20px; margin-top: 1.5rem; }
.lp-arch-wire-line { position: absolute; top: 50%; left: 10%; right: 10%; height: 1px; background: linear-gradient(90deg, transparent, rgba(var(--nc-primary-rgb),0.12) 15%, rgba(var(--nc-primary-rgb),0.12) 85%, transparent); }
.lp-arch-wire-pulse { position: absolute; top: calc(50% - 2px); left: 10%; width: 20px; height: 4px; border-radius: 2px; background: rgba(var(--nc-primary-rgb),0.4); box-shadow: 0 0 8px rgba(var(--nc-primary-rgb),0.3); animation: wirePulse 4s ease-in-out infinite; }
@keyframes wirePulse { 0% { left: 10%; opacity: 0; } 10% { opacity: 1; } 90% { opacity: 1; } 100% { left: calc(90% - 20px); opacity: 0; } }

/* Architecture CTA */
.lp-arch-cta { text-align: center; margin-top: 2.5rem; }
.lp-arch-cta-btn {
  display: inline-flex; align-items: center; gap: 10px;
  font-family: 'JetBrains Mono', 'Fira Code', 'SF Mono', monospace;
  font-size: 12px; font-weight: 600; letter-spacing: 0.12em;
  color: var(--nc-primary); text-decoration: none;
  padding: 14px 32px; border-radius: 8px;
  border: 1px solid rgba(var(--nc-primary-rgb),0.3);
  background: linear-gradient(135deg, rgba(var(--nc-primary-rgb),0.06), rgba(var(--nc-primary-rgb),0.02));
  transition: all 0.3s;
}
.lp-arch-cta-btn:hover {
  border-color: rgba(var(--nc-primary-rgb),0.6);
  background: linear-gradient(135deg, rgba(var(--nc-primary-rgb),0.12), rgba(var(--nc-primary-rgb),0.04));
  box-shadow: 0 0 30px rgba(var(--nc-primary-rgb),0.1), 0 0 60px rgba(var(--nc-primary-rgb),0.05);
  transform: translateY(-2px);
}
.lp-arch-cta-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: #00e676; box-shadow: 0 0 8px #00e676;
  animation: pulse 2s ease-in-out infinite;
}
.lp-arch-cta-arrow { opacity: 0.6; transition: transform 0.2s, opacity 0.2s; }
.lp-arch-cta-btn:hover .lp-arch-cta-arrow { opacity: 1; transform: translateX(3px); }
.lp-arch-cta-sub {
  display: block; margin-top: 10px;
  font-size: 11px; color: rgba(200,205,213,0.35); letter-spacing: 0.04em;
}
@keyframes corePulse { 0%,100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.2); opacity: 0.8; } }
@keyframes dotBloom { 0%,100% { transform: scale(1); opacity: 0.4; } 50% { transform: scale(1.8); opacity: 0; } }
@keyframes efPausePulse {
  0%, 100% {
    box-shadow: 0 0 0 0 rgba(var(--nc-primary-rgb), 0.45),
                0 0 4px 0 rgba(var(--nc-primary-rgb), 0.25);
    border-color: rgba(var(--nc-primary-rgb), 0.5);
  }
  50% {
    box-shadow: 0 0 0 5px rgba(var(--nc-primary-rgb), 0.0),
                0 0 14px 2px rgba(var(--nc-primary-rgb), 0.55);
    border-color: rgba(var(--nc-primary-rgb), 0.95);
  }
}

/* ═══ SECTIONS ═══ */
.lp-section { position: relative; z-index: 1; padding: 5rem 2rem; background: radial-gradient(ellipse 80% 50% at 50% 20%, rgba(var(--nc-primary-rgb),0.015) 0%, transparent 70%); }
.lp-section-dark { background: radial-gradient(ellipse 90% 60% at 50% 0%, rgba(var(--nc-primary-rgb),0.045) 0%, transparent 60%), rgba(4,6,12,0.65); border-top: 1px solid rgba(var(--nc-primary-rgb),0.06); border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.04); box-shadow: inset 0 1px 0 rgba(var(--nc-primary-rgb),0.06), 0 -1px 12px rgba(var(--nc-primary-rgb),0.03); }
.lp-center { text-align: center; }
.lp-h2 { font-size: 1.75rem; font-weight: 300; color: #e0e6ed; letter-spacing: 0.01em; margin-bottom: 1.25rem; text-shadow: 0 0 40px rgba(var(--nc-primary-rgb),0.08); }
.lp-body { font-size: 0.95rem; line-height: 1.8; color: #6a7a8a; max-width: 680px; margin-bottom: 3rem; }
.lp-detail-grid { display: grid; grid-template-columns: repeat(3,1fr); gap: 2rem; }
.lp-detail { padding: 1.75rem; background: rgba(10,16,24,0.6); border: 1px solid rgba(var(--nc-primary-rgb),0.06); transition: border-color 0.25s, box-shadow 0.25s; }
.lp-detail:hover { border-color: rgba(var(--nc-primary-rgb),0.12); box-shadow: 0 2px 16px rgba(0,0,0,0.15); }
.lp-detail-title { font-size: 0.9rem; font-weight: 500; color: #c8d2dc; margin-bottom: 0.75rem; border-left: 2px solid rgba(var(--nc-primary-rgb),0.15); padding-left: 0.75rem; }
.lp-detail-text { font-size: 0.825rem; line-height: 1.7; color: #5a6a7a; }
.lp-stack-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: 1.5rem; margin-bottom: 3rem; }
.lp-stack-item { text-align: center; padding: 1.5rem 0.5rem; border: 1px solid rgba(var(--nc-primary-rgb),0.08); background: rgba(var(--nc-primary-rgb),0.02); transition: border-color 0.25s, background 0.25s; }
.lp-stack-item:hover { border-color: rgba(var(--nc-primary-rgb),0.18); background: rgba(var(--nc-primary-rgb),0.04); }
.lp-stack-val { font-size: 2rem; font-weight: 300; color: var(--nc-primary); font-family: 'IBM Plex Mono', monospace; margin-bottom: 0.4rem; }
.lp-stack-label { font-size: 0.7rem; letter-spacing: 0.06em; color: #556677; text-transform: uppercase; }
.lp-tech-row { display: flex; flex-wrap: wrap; gap: 0.5rem; justify-content: center; }
.lp-tech { font-size: 0.7rem; letter-spacing: 0.05em; padding: 0.35rem 0.85rem; border: 1px solid rgba(var(--nc-primary-rgb),0.1); color: #556677; font-family: 'IBM Plex Mono', monospace; transition: border-color 0.2s, color 0.2s; }
.lp-tech:hover { border-color: rgba(var(--nc-primary-rgb),0.3); color: var(--nc-primary); }
.lp-flow { display: flex; flex-direction: column; }
.lp-flow-step { display: flex; gap: 2rem; padding: 2rem 0; border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.04); border-left: 2px solid transparent; transition: background 0.25s, border-left-color 0.25s; }
.lp-flow-step:last-child { border-bottom: none; }
.lp-flow-step:hover { background: rgba(var(--nc-primary-rgb),0.015); border-left-color: rgba(var(--nc-primary-rgb),0.15); }
.lp-flow-step:hover .lp-flow-num { opacity: 0.7; }
.lp-flow-num { font-size: 0.75rem; font-family: 'IBM Plex Mono', monospace; color: var(--nc-primary); opacity: 0.4; padding-top: 0.15rem; flex-shrink: 0; width: 2rem; transition: opacity 0.25s; }
.lp-flow-title { font-size: 1rem; font-weight: 500; color: #d0d8e0; margin-bottom: 0.5rem; }
.lp-flow-text { font-size: 0.875rem; line-height: 1.7; color: #5a6a7a; max-width: 560px; }
.lp-beta-card { padding: 4rem 3rem; border: 1px solid rgba(var(--nc-primary-rgb),0.1); background: rgba(var(--nc-primary-rgb),0.02); max-width: 800px; margin: 0 auto; box-shadow: 0 8px 40px rgba(0,0,0,0.3); transition: border-color 0.3s; }
.lp-beta-card:hover { border-color: rgba(var(--nc-primary-rgb),0.2); }
.lp-beta-badge { display: inline-block; font-size: 0.65rem; letter-spacing: 0.2em; font-weight: 600; color: #060810; background: var(--nc-primary); padding: 0.25rem 0.75rem; margin-bottom: 1.5rem; font-family: 'IBM Plex Mono', monospace; box-shadow: 0 0 12px rgba(var(--nc-primary-rgb),0.3); }
.lp-beta-facts { display: flex; justify-content: center; gap: 0.75rem; margin-top: 2rem; flex-wrap: wrap; font-size: 0.8rem; color: #556677; }
.lp-dot { color: rgba(var(--nc-primary-rgb),0.3); }
.lp-beta-wipe { margin-top: 2rem; padding: 1rem 1.5rem; border: 1px solid rgba(255,145,0,0.18); background: rgba(255,145,0,0.03); font-size: 0.78rem; line-height: 1.75; color: #5a4a3a; max-width: 640px; margin-left: auto; margin-right: auto; }
.lp-beta-wipe-label { display: block; font-size: 0.6rem; letter-spacing: 0.16em; font-family: 'IBM Plex Mono', monospace; font-weight: 600; color: #ff9100; opacity: 0.7; margin-bottom: 0.5rem; }

/* ═══ FOOTER ═══ */
.lp-footer { position: relative; z-index: 1; border-top: 1px solid rgba(var(--nc-primary-rgb),0.06); padding: 2.5rem 2rem; background: radial-gradient(ellipse 80% 50% at 50% 100%, rgba(var(--nc-primary-rgb),0.015) 0%, transparent 70%); }
.lp-footer-top { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 2rem; }
.lp-footer-brand { display: flex; flex-direction: column; gap: 0.35rem; }
.lp-footer-name { font-size: 0.8rem; letter-spacing: 0.18em; color: #778899; }
.lp-footer-tagline { font-size: 0.7rem; color: #445566; }
.lp-footer-links { display: flex; gap: 1.5rem; flex-wrap: wrap; }
.lp-footer-links a { font-size: 0.75rem; color: #445566; text-decoration: none; transition: color 0.2s; background-image: linear-gradient(rgba(var(--nc-primary-rgb),0.4), rgba(var(--nc-primary-rgb),0.4)); background-size: 0% 1px; background-position: 0 100%; background-repeat: no-repeat; transition: color 0.2s, background-size 0.3s; }
.lp-footer-links a:hover { color: var(--nc-primary); background-size: 100% 1px; }
.lp-footer-bottom { padding-top: 1.5rem; border-top: 1px solid rgba(var(--nc-primary-rgb),0.04); font-size: 0.7rem; color: #334455; }

/* ═══ MCP CONNECTOR — TALK TO THE PROTOCOL FROM CLAUDE (§pass71 polish 2) ═══ */
/* Rides the page-wide .lp-ambient (grid + scan + glows).  Models the section  */
/* base + typography + tiles on the sibling .ag (Agent Bundle) section above.  */
/* Cyan-primary themed (sibling .ag uses green-AVT).                            */

.mcpc {
  padding: 5rem 0;
  position: relative;
  border-top:    1px solid rgba(var(--nc-primary-rgb),0.06);
  border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.06);
  background: linear-gradient(180deg,
    rgba(var(--nc-primary-rgb),0.02) 0%,
    transparent 100%);
}

/* ── Centered header (mirrors .ag-header / .ag-eyebrow / .ag-h2 / .ag-lead) ── */
.mcpc-header {
  text-align: center;
  max-width: 760px;
  margin: 0 auto 3rem;
  padding: 0 2rem;
}
.mcpc-eyebrow {
  display: inline-flex; align-items: center; gap: 0.6rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.56rem; font-weight: 600; letter-spacing: 0.25em;
  color: rgba(var(--nc-primary-rgb),0.5);
  margin-bottom: 1rem;
  white-space: nowrap;
}
.mcpc-eyebrow-dot {
  width: 5px; height: 5px; border-radius: 50%;
  background: var(--nc-primary);
  box-shadow: 0 0 8px rgba(var(--nc-primary-rgb),0.55);
  animation: mcpcDotPulse 3.4s ease-in-out infinite;
}
@keyframes mcpcDotPulse {
  0%,100% { opacity: 0.55; box-shadow: 0 0 5px  rgba(var(--nc-primary-rgb),0.4); }
  50%     { opacity: 1;    box-shadow: 0 0 12px rgba(var(--nc-primary-rgb),0.85); }
}
.mcpc-h2 {
  font-size: clamp(1.6rem, 3.5vw, 2.4rem);
  font-weight: 300; line-height: 1.2;
  color: rgba(255,255,255,0.92);
  margin: 0 0 1rem;
  letter-spacing: -0.01em;
}
.mcpc-h2-accent {
  display: block;
  color: var(--nc-primary);
  font-weight: 300;
}
.mcpc-lead {
  max-width: 680px; margin: 0 auto;
  font-size: 0.88rem; line-height: 1.7;
  color: rgba(255,255,255,0.55);
}
.mcpc-lead strong { color: rgba(255,255,255,0.85); font-weight: 500; }
.mcpc-lead code {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.82rem;
  background: rgba(var(--nc-primary-rgb),0.08);
  padding: 0.15em 0.4em;
  border-radius: 2px;
  color: rgba(var(--nc-primary-rgb),0.8);
}

/* ── Hero stats — modeled on .ag-download-grid (single card, 4 columns) ── */
.mcpc-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  background: rgba(var(--nc-primary-rgb),0.025);
  border: 1px solid rgba(var(--nc-primary-rgb),0.12);
  padding: 1.5rem 0;
  margin-bottom: 1rem;
}
.mcpc-stat {
  text-align: center;
  padding: 0.25rem 1rem;
  border-left: 1px solid rgba(255,255,255,0.04);
  transition: background 0.25s;
}
.mcpc-stat:first-child { border-left: none; }
.mcpc-stat:hover { background: rgba(var(--nc-primary-rgb),0.025); }
.mcpc-num {
  display: block;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 1.95rem; font-weight: 200;
  color: rgba(var(--nc-primary-rgb),0.9);
  line-height: 1.05; margin-bottom: 0.5rem;
  letter-spacing: -0.01em;
}
.mcpc-num-pct {
  font-size: 0.55em; opacity: 0.55;
  margin-left: 0.05em; font-weight: 300;
}
.mcpc-num-label {
  display: block;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.55rem; font-weight: 700; letter-spacing: 0.18em;
  color: rgba(255,255,255,0.55);
  text-transform: uppercase;
  margin-bottom: 0.3rem;
}
.mcpc-num-sub {
  display: block;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.58rem;
  color: rgba(255,255,255,0.28);
  letter-spacing: 0.04em;
}

/* ── Tier cascade — five rows aligned with .lp-container width ── */
.mcpc-tiers {
  display: flex; flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 1rem;
}
.mcpc-tier {
  display: grid;
  grid-template-columns: 180px 1fr auto;
  gap: 1.5rem; align-items: center;
  padding: 0.9rem 1.5rem;
  background: rgba(1,3,8,0.5);
  border: 1px solid rgba(var(--nc-primary-rgb),0.08);
  border-left: 2px solid var(--mcpc-tier-color, rgba(var(--nc-primary-rgb),0.4));
  transition: border-color 0.25s, background 0.25s, transform 0.2s;
}
.mcpc-tier:hover {
  background: rgba(1,3,8,0.7);
  border-color: rgba(var(--nc-primary-rgb),0.2);
  transform: translateX(1px);
}
.mcpc-tier[data-tier="t0"]    { --mcpc-tier-color: rgba(255,255,255,0.3);  }
.mcpc-tier[data-tier="t1"]    { --mcpc-tier-color: rgba(0,230,118,0.5);    }
.mcpc-tier[data-tier="t2"]    { --mcpc-tier-color: rgba(255,215,0,0.55);   }
.mcpc-tier[data-tier="t3"]    { --mcpc-tier-color: rgba(139,92,246,0.6);   }
.mcpc-tier[data-tier="admin"] { --mcpc-tier-color: rgba(245,80,80,0.6);    }

.mcpc-tier-head {
  display: flex; flex-direction: column; gap: 0.3rem;
  min-width: 0;
}
.mcpc-tier-badge {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.58rem; font-weight: 700; letter-spacing: 0.18em;
  color: var(--mcpc-tier-color, var(--nc-primary));
  filter: brightness(1.35);
}
.mcpc-tier-count {
  display: flex; align-items: baseline; gap: 0.35rem;
  font-family: 'IBM Plex Mono', monospace;
}
.mcpc-tier-n {
  font-size: 1.5rem; font-weight: 200; line-height: 1;
  color: rgba(255,255,255,0.9);
}
.mcpc-tier-count-sfx {
  font-size: 0.6rem;
  color: rgba(255,255,255,0.3);
  letter-spacing: 0.06em;
}

.mcpc-tier-meta {
  font-size: 0.78rem; line-height: 1.55;
  color: rgba(255,255,255,0.5);
}
.mcpc-tier-auth {
  display: inline-block;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem;
  color: var(--mcpc-tier-color, var(--nc-primary));
  filter: brightness(1.3);
  padding: 0.1rem 0.45rem;
  border: 1px solid var(--mcpc-tier-color, var(--nc-primary));
  background: rgba(0,0,0,0.25);
  margin-right: 0.3rem;
}

.mcpc-tier-tools {
  display: flex; flex-wrap: wrap; gap: 0.3rem;
  justify-content: flex-end;
  max-width: 460px;
}
.mcpc-tool {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem;
  color: rgba(255,255,255,0.6);
  background: rgba(var(--nc-primary-rgb),0.04);
  border: 1px solid rgba(var(--nc-primary-rgb),0.10);
  padding: 0.2rem 0.55rem;
  border-radius: 2px;
  transition: color 0.2s, background 0.2s, border-color 0.2s;
  white-space: nowrap;
}
.mcpc-tool:hover {
  color: rgba(255,255,255,0.9);
  border-color: var(--mcpc-tier-color, rgba(var(--nc-primary-rgb),0.3));
  background: rgba(var(--nc-primary-rgb),0.07);
}
.mcpc-tool-more {
  color: rgba(255,255,255,0.3);
  background: transparent;
  border-color: rgba(255,255,255,0.08);
  font-style: italic;
}
.mcpc-tool-more:hover {
  color: rgba(255,255,255,0.55);
  border-color: rgba(255,255,255,0.18);
  background: transparent;
}
.mcpc-tier[data-tier="admin"] .mcpc-tool:not(.mcpc-tool-more) {
  color: rgba(245,150,150,0.85);
  background: rgba(245,80,80,0.05);
  border-color: rgba(245,80,80,0.15);
}
.mcpc-tier[data-tier="admin"] .mcpc-tool:not(.mcpc-tool-more):hover {
  color: rgba(255,200,200,1);
  border-color: rgba(245,100,100,0.5);
  background: rgba(245,80,80,0.1);
}

/* ── Architecture mini-strip — modeled on .ag-onboard ── */
.mcpc-arch {
  display: grid;
  grid-template-columns: auto 1fr auto 1fr auto;
  gap: 1.25rem; align-items: center;
  padding: 1.25rem 2rem;
  margin-bottom: 1rem;
  background: rgba(1,3,8,0.5);
  border: 1px solid rgba(var(--nc-primary-rgb),0.10);
}
.mcpc-arch-node {
  text-align: center;
  padding: 0.55rem 1.2rem;
  border: 1px solid rgba(var(--nc-primary-rgb),0.18);
  background: rgba(var(--nc-primary-rgb),0.03);
  min-width: 120px;
  transition: border-color 0.25s, background 0.25s;
}
.mcpc-arch-node:hover {
  border-color: rgba(var(--nc-primary-rgb),0.4);
  background: rgba(var(--nc-primary-rgb),0.06);
}
.mcpc-arch-claude {
  border-color: rgba(199,154,74,0.3);
  background: rgba(199,154,74,0.04);
}
.mcpc-arch-claude:hover {
  border-color: rgba(199,154,74,0.55);
  background: rgba(199,154,74,0.07);
}
.mcpc-arch-bridge {
  border-color: rgba(255,255,255,0.12);
  background: rgba(255,255,255,0.015);
}
.mcpc-arch-bridge:hover {
  border-color: rgba(255,255,255,0.3);
  background: rgba(255,255,255,0.03);
}
.mcpc-arch-node-label {
  display: block;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem; font-weight: 700; letter-spacing: 0.18em;
  color: rgba(var(--nc-primary-rgb),0.85);
  margin-bottom: 0.2rem;
}
.mcpc-arch-claude .mcpc-arch-node-label { color: rgba(199,154,74,0.95); }
.mcpc-arch-bridge .mcpc-arch-node-label { color: rgba(255,255,255,0.78); }
.mcpc-arch-node-sub {
  display: block;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.55rem;
  color: rgba(255,255,255,0.3);
  letter-spacing: 0.04em; line-height: 1.45;
}
.mcpc-arch-link {
  display: flex; flex-direction: column; align-items: center;
  gap: 0.4rem; padding: 0 0.5rem;
}
.mcpc-arch-link-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.52rem;
  color: rgba(255,255,255,0.32);
  letter-spacing: 0.04em;
  text-align: center; line-height: 1.4;
}
.mcpc-arch-line {
  position: relative;
  display: block; width: 100%; height: 1px;
  background: linear-gradient(90deg,
    rgba(var(--nc-primary-rgb),0.12) 0%,
    rgba(var(--nc-primary-rgb),0.32) 50%,
    rgba(var(--nc-primary-rgb),0.12) 100%);
  overflow: hidden;
}
.mcpc-arch-line::after {
  content: ''; position: absolute; top: -1px; left: -20%;
  width: 20%; height: 2px;
  background: linear-gradient(90deg, transparent, var(--nc-primary), transparent);
  filter: blur(1px);
  animation: mcpcArchFlow 4s linear infinite;
}
@keyframes mcpcArchFlow {
  0%   { left: -20%; opacity: 0.3; }
  10%  { opacity: 1; }
  90%  { opacity: 1; }
  100% { left: 120%; opacity: 0.3; }
}
.mcpc-arch-link:nth-of-type(4) .mcpc-arch-line::after { animation-delay: 2s; }

/* ── Live workflow demo — clean .ag-panel-style card ── */
.mcpc-demo {
  margin-bottom: 1.5rem;
  background: rgba(1,3,8,0.6);
  border: 1px solid rgba(var(--nc-primary-rgb),0.10);
  box-shadow: 0 4px 20px rgba(0,0,0,0.2);
}
.mcpc-demo-head {
  display: flex; justify-content: space-between; align-items: center;
  padding: 0.7rem 1.5rem;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.08);
  background: rgba(var(--nc-primary-rgb),0.025);
}
.mcpc-demo-badge {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.55rem; font-weight: 700; letter-spacing: 0.2em;
  color: rgba(var(--nc-primary-rgb),0.85);
}
.mcpc-demo-meta {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.55rem;
  color: rgba(255,255,255,0.3);
  letter-spacing: 0.04em;
}
.mcpc-demo-body {
  padding: 1.4rem 1.75rem;
  display: flex; flex-direction: column; gap: 1.1rem;
}
.mcpc-demo-msg {
  display: grid; grid-template-columns: 64px 1fr;
  gap: 1rem; align-items: flex-start;
}
.mcpc-demo-role {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.55rem; font-weight: 700; letter-spacing: 0.18em;
  padding: 0.22rem 0.45rem;
  border: 1px solid rgba(var(--nc-primary-rgb),0.25);
  background: rgba(var(--nc-primary-rgb),0.05);
  color: rgba(var(--nc-primary-rgb),0.95);
  text-align: center;
  align-self: flex-start;
}
.mcpc-demo-msg-claude .mcpc-demo-role {
  color: rgba(199,154,74,0.95);
  border-color: rgba(199,154,74,0.35);
  background: rgba(199,154,74,0.06);
}
.mcpc-demo-text {
  font-size: 0.82rem; line-height: 1.7;
  color: rgba(255,255,255,0.78);
  padding-top: 0.1rem;
}
.mcpc-demo-did {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.85em;
  color: rgba(var(--nc-primary-rgb),0.85);
  background: rgba(var(--nc-primary-rgb),0.06);
  padding: 0.05rem 0.35rem;
  border-radius: 2px;
}
.mcpc-demo-call {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.75rem;
  color: rgba(255,255,255,0.55);
  line-height: 1.8;
}
.mcpc-demo-arrow {
  color: rgba(199,154,74,0.7);
  margin-right: 0.4rem;
}
.mcpc-demo-fn { color: rgba(199,154,74,0.95); }
.mcpc-demo-arg { color: rgba(var(--nc-primary-rgb),0.7); }
.mcpc-demo-result {
  margin-top: 0.6rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  color: rgba(0,230,118,0.7);
  line-height: 1.6;
}
.mcpc-demo-check {
  display: inline-block; margin-right: 0.4rem;
  color: #00e676;
  text-shadow: 0 0 6px rgba(0,230,118,0.5);
}

/* ── Connect in 30 seconds — modeled on .ag-link-cta ── */
.mcpc-connect {
  /* aligned with .lp-container edge — no extra padding */
}
.mcpc-connect-head {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.56rem; font-weight: 700; letter-spacing: 0.25em;
  color: rgba(var(--nc-primary-rgb),0.55);
  margin-bottom: 1rem;
}
.mcpc-connect-grid {
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 1rem; margin-bottom: 1.25rem;
}
.mcpc-endpoint {
  display: flex; flex-direction: column; gap: 0.55rem;
  padding: 1rem 1.25rem;
  background: rgba(var(--nc-primary-rgb),0.04);
  border: 1px solid rgba(var(--nc-primary-rgb),0.20);
  cursor: pointer; text-align: left;
  font-family: inherit;
  transition: background 0.2s, border-color 0.2s, transform 0.2s, box-shadow 0.2s;
  border-radius: 0;
}
.mcpc-endpoint:hover {
  background: rgba(var(--nc-primary-rgb),0.08);
  border-color: rgba(var(--nc-primary-rgb),0.45);
  box-shadow: 0 0 20px rgba(var(--nc-primary-rgb),0.12);
  transform: translateY(-1px);
}
.mcpc-endpoint-admin {
  background: rgba(245,80,80,0.04);
  border-color: rgba(245,80,80,0.22);
}
.mcpc-endpoint-admin:hover {
  background: rgba(245,80,80,0.08);
  border-color: rgba(245,80,80,0.5);
  box-shadow: 0 0 20px rgba(245,80,80,0.12);
}
.mcpc-endpoint-top {
  display: flex; justify-content: space-between; align-items: baseline;
}
.mcpc-endpoint-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem; font-weight: 700; letter-spacing: 0.18em;
  color: rgba(var(--nc-primary-rgb),0.85);
}
.mcpc-endpoint-admin .mcpc-endpoint-label { color: rgba(245,120,120,0.95); }
.mcpc-endpoint-count {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem;
  color: rgba(255,255,255,0.3);
  letter-spacing: 0.04em;
}
.mcpc-endpoint-url {
  display: block;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.85rem;
  color: rgba(255,255,255,0.85);
  background: rgba(0,0,0,0.3);
  padding: 0.45rem 0.7rem;
  border-radius: 2px;
}
.mcpc-endpoint-copy {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.55rem;
  color: rgba(255,255,255,0.3);
  letter-spacing: 0.04em;
}

.mcpc-connect-cta {
  display: flex; gap: 2rem; flex-wrap: wrap;
  padding-top: 0.5rem;
}
.mcpc-connect-link {
  display: inline-flex; align-items: center; gap: 0.5rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem; font-weight: 500;
  color: rgba(var(--nc-primary-rgb),0.85);
  text-decoration: none;
  letter-spacing: 0.04em;
  padding: 0.25rem 0;
  border-bottom: 1px solid transparent;
  transition: color 0.2s, border-color 0.2s;
}
.mcpc-connect-link:hover {
  color: rgba(255,255,255,0.95);
  border-bottom-color: var(--nc-primary);
}
.mcpc-connect-link-arrow {
  font-size: 0.85rem; opacity: 0.7;
}
.mcpc-connect-link-mcp { color: rgba(139,92,246,0.85); }
.mcpc-connect-link-mcp:hover {
  color: rgba(196,176,255,1);
  border-bottom-color: rgba(139,92,246,0.7);
}

/* ── Accessibility ── */
@media (prefers-reduced-motion: reduce) {
  .mcpc-eyebrow-dot      { animation: none; opacity: 0.85; }
  .mcpc-arch-line::after { display: none; }
}
.mcpc-endpoint:focus-visible,
.mcpc-arch-node:focus-visible,
.mcpc-tier:focus-visible,
.mcpc-connect-link:focus-visible {
  outline: 2px solid var(--nc-primary);
  outline-offset: 3px;
}
.mcpc-endpoint-admin:focus-visible {
  outline-color: rgba(245,120,120,0.85);
}

/* ── Responsive breakpoints ── */
@media (max-width: 1100px) {
  .mcpc-stats { grid-template-columns: repeat(2, 1fr); padding: 1rem 0; }
  .mcpc-stat { padding: 1rem; border-left: none; border-top: 1px solid rgba(255,255,255,0.04); }
  .mcpc-stat:nth-child(-n+2) { border-top: none; }
  .mcpc-stat:nth-child(odd) { border-right: 1px solid rgba(255,255,255,0.04); }
  .mcpc-tier { grid-template-columns: 1fr; gap: 0.75rem; padding: 1rem 1.25rem; }
  .mcpc-tier-head { flex-direction: row; align-items: center; justify-content: space-between; }
  .mcpc-tier-tools { justify-content: flex-start; max-width: 100%; }
  .mcpc-connect-grid { grid-template-columns: 1fr; }
}
@media (max-width: 900px) {
  .mcpc-arch {
    grid-template-columns: 1fr;
    padding: 1rem 1.25rem; gap: 0.55rem;
  }
  .mcpc-arch-node { width: 100%; min-width: 0; padding: 0.55rem 1rem; }
  .mcpc-arch-link { flex-direction: row; width: 100%; gap: 0.75rem; padding: 0; }
  .mcpc-arch-link-label { flex: 1; text-align: left; }
  .mcpc-arch-line {
    flex: 1;
    height: 1px;
    background: linear-gradient(90deg,
      rgba(var(--nc-primary-rgb),0.12),
      rgba(var(--nc-primary-rgb),0.3),
      rgba(var(--nc-primary-rgb),0.12));
  }
  .mcpc-arch-line::after { display: none; }
}
@media (max-width: 640px) {
  .mcpc { padding: 3.5rem 0; }
  .mcpc-header { padding: 0 1.25rem; }
  .mcpc-stats, .mcpc-tiers, .mcpc-arch, .mcpc-demo, .mcpc-connect {
    margin-left: 1.25rem; margin-right: 1.25rem;
  }
  .mcpc-tiers, .mcpc-connect { padding: 0; }
  .mcpc-num { font-size: 1.65rem; }
  .mcpc-demo-msg { grid-template-columns: 1fr; gap: 0.5rem; }
  .mcpc-demo-role { width: 60px; }
  .mcpc-demo-call { font-size: 0.72rem; word-break: break-all; }
  .mcpc-endpoint-url { font-size: 0.75rem; word-break: break-all; }
}


/* ═══ ZKP ATTESTATION ═══ */
.zkp-eyebrow-tag { font-size: 0.62rem; letter-spacing: 0.2em; font-weight: 600; color: #b388ff; font-family: 'IBM Plex Mono', monospace; margin-bottom: 1.25rem; opacity: 0.75; }
.zkp-flow { display: grid; grid-template-columns: 1fr auto 1fr; gap: 2rem; align-items: center; margin: 2.5rem 0; }
.zkp-col-label { font-size: 0.58rem; letter-spacing: 0.18em; color: #445566; font-family: 'IBM Plex Mono', monospace; margin-bottom: 0.75rem; font-weight: 600; }
.zkp-box { border: 1px solid rgba(179,136,255,0.12); background: rgba(6,8,18,0.8); overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.2); }
.zkp-box-agent { border-color: rgba(179,136,255,0.15); }
.zkp-box-registry { border-color: rgba(var(--nc-primary-rgb),0.12); }
.zkp-region { padding: 1rem 1.25rem; }
.zkp-private { background: rgba(179,136,255,0.04); border-bottom: 1px solid rgba(179,136,255,0.08); }
.zkp-public { background: rgba(var(--nc-primary-rgb),0.02); }
.zkp-region-label { font-size: 0.55rem; letter-spacing: 0.14em; font-family: 'IBM Plex Mono', monospace; margin-bottom: 0.6rem; font-weight: 600; }
.zkp-private .zkp-region-label { color: #b388ff; }
.zkp-public .zkp-region-label { color: var(--nc-primary); }
.zkp-line { display: block; font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem; color: #7a9a8a; line-height: 1.8; background: none; }
.zkp-private .zkp-line { color: #9a7abb; }
.zkp-never { font-size: 0.58rem; color: #334455; font-family: 'IBM Plex Mono', monospace; margin-top: 0.4rem; font-style: italic; }
.zkp-badge-row { display: flex; gap: 0.5rem; margin-top: 0.75rem; }
.zkp-cmd { font-size: 0.62rem; font-family: 'IBM Plex Mono', monospace; color: #667788; border: 1px solid rgba(100,100,150,0.15); padding: 0.2rem 0.55rem; background: rgba(100,100,150,0.05); }
.zkp-proof-chip { margin-top: 0.6rem; font-size: 0.65rem; font-family: 'IBM Plex Mono', monospace; color: #b388ff; border: 1px solid rgba(179,136,255,0.25); padding: 0.3rem 0.75rem; text-align: center; background: rgba(179,136,255,0.06); letter-spacing: 0.08em; animation: zkpChipPulse 3s ease-in-out infinite; }
@keyframes zkpChipPulse { 0%,100% { box-shadow: 0 0 6px rgba(179,136,255,0.1); } 50% { box-shadow: 0 0 14px rgba(179,136,255,0.2); } }
.zkp-arrow { display: flex; flex-direction: column; align-items: center; gap: 0.5rem; }
.zkp-arrow-line { width: 2px; height: 60px; background: linear-gradient(180deg, rgba(179,136,255,0.4), rgba(var(--nc-primary-rgb),0.4)); }
.zkp-arrow-text { font-size: 0.6rem; font-family: 'IBM Plex Mono', monospace; color: #4a5a7a; text-align: center; line-height: 1.6; }
.zkp-arrow-sub { color: #2a3a4a; }
.zkp-arrowhead { font-size: 0.9rem; color: var(--nc-primary); opacity: 0.5; }
.zkp-verify-step { display: flex; gap: 0.75rem; align-items: flex-start; padding: 0.55rem 1.25rem; border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.04); }
.zkp-verify-step:last-child { border-bottom: none; }
.zkp-verify-n { font-size: 0.62rem; font-family: 'IBM Plex Mono', monospace; color: var(--nc-primary); opacity: 0.5; flex-shrink: 0; width: 1rem; padding-top: 0.1rem; }
.zkp-verify-text { font-size: 0.72rem; font-family: 'IBM Plex Mono', monospace; color: #6a8a9a; line-height: 1.6; }
.zkp-result { display: flex; align-items: center; gap: 0.6rem; margin-top: 0.75rem; padding: 0.6rem 0.8rem; border: 1px solid rgba(0,230,118,0.2); background: rgba(0,230,118,0.04); }
.zkp-result-check { font-size: 1.1rem; color: #00e676; }
.zkp-result-text { font-size: 0.68rem; font-family: 'IBM Plex Mono', monospace; color: #4a8a6a; line-height: 1.5; }
.zkp-circuits { display: grid; grid-template-columns: 1fr 1fr; gap: 1.25rem; margin-top: 2.5rem; }
.zkp-circuit { border: 1px solid rgba(179,136,255,0.1); background: rgba(6,4,14,0.7); padding: 1.5rem; transition: border-color 0.25s; }
.zkp-circuit:hover { border-color: rgba(179,136,255,0.22); }
.zkp-circuit-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.75rem; gap: 1rem; }
.zkp-circuit-id { font-size: 0.7rem; font-family: 'IBM Plex Mono', monospace; color: #b388ff; font-weight: 500; }
.zkp-circuit-scheme { font-size: 0.55rem; font-family: 'IBM Plex Mono', monospace; color: #3a4a5a; white-space: nowrap; }
.zkp-circuit-desc { font-size: 0.78rem; line-height: 1.7; color: #556677; margin-bottom: 1.25rem; }
.zkp-circuit-io { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
.zkp-io-col { display: flex; flex-direction: column; gap: 0.25rem; }
.zkp-io-label { font-size: 0.52rem; letter-spacing: 0.14em; font-family: 'IBM Plex Mono', monospace; margin-bottom: 0.35rem; font-weight: 600; }
.zkp-io-pub { color: var(--nc-primary); }
.zkp-io-priv { color: #b388ff; }
.zkp-io-item { font-size: 0.62rem; font-family: 'IBM Plex Mono', monospace; padding: 0.25rem 0.5rem; display: block; background: none; }
.zkp-io-item-pub { color: #6a8a9a; border-left: 2px solid rgba(var(--nc-primary-rgb),0.2); }
.zkp-io-item-priv { color: #8a6a9a; border-left: 2px solid rgba(179,136,255,0.2); }

/* ═══ EIGENTRUST++ ═══ */
.et-eyebrow-tag { font-size: 0.62rem; letter-spacing: 0.2em; font-weight: 600; color: #ffd740; font-family: 'IBM Plex Mono', monospace; margin-bottom: 1.25rem; opacity: 0.7; }
.et-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 2.5rem; margin: 2rem 0; }
.et-section-label { font-size: 0.55rem; letter-spacing: 0.18em; color: #3a4a5a; font-family: 'IBM Plex Mono', monospace; font-weight: 600; margin-bottom: 1rem; }
.et-steps { display: flex; flex-direction: column; gap: 0.6rem; margin-bottom: 2rem; }
.et-step { display: flex; gap: 1rem; padding: 0.75rem 1rem; background: rgba(255,215,64,0.02); border: 1px solid rgba(255,215,64,0.06); border-left: 2px solid rgba(255,215,64,0.2); transition: border-left-color 0.25s, background 0.25s; }
.et-step:hover { border-left-color: rgba(255,215,64,0.45); background: rgba(255,215,64,0.035); }
.et-step-n { font-size: 0.6rem; font-family: 'IBM Plex Mono', monospace; color: #ffd740; opacity: 0.5; flex-shrink: 0; padding-top: 0.15rem; width: 1.5rem; }
.et-step-name { font-size: 0.78rem; font-weight: 500; color: #c0cad4; margin-bottom: 0.2rem; }
.et-step-desc { font-size: 0.72rem; line-height: 1.65; color: #556677; }
.et-formula-block { background: rgba(2,4,10,0.8); border: 1px solid rgba(255,215,64,0.1); padding: 1.25rem 1.5rem; box-shadow: 0 4px 20px rgba(0,0,0,0.2); }
.et-formula-label { font-size: 0.52rem; letter-spacing: 0.16em; color: #556677; font-family: 'IBM Plex Mono', monospace; margin-bottom: 0.75rem; }
.et-formula { font-size: 1.1rem; font-family: 'IBM Plex Mono', monospace; color: #ffd740; letter-spacing: 0.05em; margin-bottom: 0.75rem; }
.et-formula sup { font-size: 0.55em; }
.et-formula-params { display: flex; gap: 1.5rem; flex-wrap: wrap; margin-bottom: 0.6rem; }
.et-fparam { font-size: 0.65rem; font-family: 'IBM Plex Mono', monospace; color: #4a6070; }
.et-fparam em { font-style: normal; color: #ffd740; opacity: 0.7; }
.et-converge { font-size: 0.65rem; font-family: 'IBM Plex Mono', monospace; color: #3a5a4a; padding-top: 0.5rem; border-top: 1px solid rgba(255,215,64,0.06); }
.et-signals { display: flex; flex-direction: column; gap: 0.5rem; margin-bottom: 0.5rem; }
.et-signal { display: flex; gap: 0.75rem; align-items: flex-start; padding: 0.6rem 0.9rem; border: 1px solid rgba(100,120,140,0.06); background: rgba(6,8,14,0.5); }
.et-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; margin-top: 0.35rem; }
.et-dot-green { background: #00e676; box-shadow: 0 0 5px rgba(0,230,118,0.5); }
.et-dot-red { background: #ff5252; box-shadow: 0 0 5px rgba(255,82,82,0.5); }
.et-dot-cyan { background: var(--nc-primary); box-shadow: 0 0 5px rgba(var(--nc-primary-rgb),0.5); }
.et-dot-purple { background: #b388ff; box-shadow: 0 0 5px rgba(179,136,255,0.5); }
.et-sig-event { font-size: 0.72rem; font-family: 'IBM Plex Mono', monospace; color: #c0cad4; margin-bottom: 0.15rem; }
.et-sig-effect { font-size: 0.65rem; color: #4a6070; font-family: 'IBM Plex Mono', monospace; }
.et-defenses { display: flex; flex-direction: column; gap: 0.4rem; }
.et-defense { padding: 0.6rem 0.9rem; border: 1px solid rgba(255,82,82,0.06); background: rgba(6,2,8,0.4); }
.et-def-name { font-size: 0.72rem; font-weight: 500; color: #b0bec5; margin-bottom: 0.2rem; font-family: 'IBM Plex Mono', monospace; }
.et-def-desc { font-size: 0.68rem; line-height: 1.6; color: #445566; }

/* ═══ SECTION HEADERS ═══ */
.sec-eyebrow { display: inline-block; font-size: 0.6rem; letter-spacing: 0.22em; font-weight: 600; color: var(--nc-primary); border: 1px solid rgba(var(--nc-primary-rgb),0.2); padding: 0.25rem 0.75rem; margin-bottom: 1.5rem; font-family: 'IBM Plex Mono', monospace; background: rgba(var(--nc-primary-rgb),0.04); box-shadow: 0 0 10px rgba(var(--nc-primary-rgb),0.06); }
.sec-eyebrow-b { color: #ff9100; border-color: rgba(255,145,0,0.2); background: rgba(255,145,0,0.04); box-shadow: 0 0 10px rgba(255,145,0,0.06); }
.eng-h3 { font-size: 1.35rem; font-weight: 300; color: #e0e6ed; margin: 0 0 0.75rem; letter-spacing: -0.01em; }
.eng-body { font-size: 0.9rem; line-height: 1.8; color: #6a7a8a; max-width: 720px; margin-bottom: 1.75rem; }
.eng-divider { height: 1px; background: linear-gradient(90deg, transparent, rgba(var(--nc-primary-rgb),0.08) 30%, rgba(var(--nc-primary-rgb),0.08) 70%, transparent); margin: 3.5rem 0 2.5rem; }

/* ═══ VETOKEN GOVERNANCE ═══ */
.vt-eyebrow-tag { font-size: 0.62rem; letter-spacing: 0.2em; font-weight: 600; color: #ffd740; font-family: 'IBM Plex Mono', monospace; margin-bottom: 1rem; opacity: 0.8; }
.vt-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 2.5rem; margin: 1.5rem 0 0; }
.vt-formula-label { font-size: 0.52rem; letter-spacing: 0.16em; color: #445566; font-family: 'IBM Plex Mono', monospace; margin-bottom: 0.75rem; }
.vt-formula { font-size: 1.05rem; font-family: 'IBM Plex Mono', monospace; color: #ffd740; margin-bottom: 1.25rem; letter-spacing: 0.02em; }
.vt-formula sub { font-size: 0.6em; }
.vt-formula-params { display: flex; flex-direction: column; gap: 0.35rem; margin-bottom: 1rem; }
.vt-param { display: grid; grid-template-columns: 70px 1fr; gap: 0.75rem; padding: 0.35rem 0; border-bottom: 1px solid rgba(255,215,64,0.05); align-items: center; }
.vt-psym { font-family: 'IBM Plex Mono', monospace; font-size: 0.7rem; color: #ffd740; opacity: 0.8; }
.vt-pdef { font-size: 0.7rem; color: #4a6070; }
.vt-note { font-size: 0.72rem; line-height: 1.65; color: #3a5060; font-style: italic; padding: 0.75rem 1rem; border-left: 2px solid rgba(255,215,64,0.15); background: rgba(255,215,64,0.02); }
.vt-tiers-label { font-size: 0.55rem; letter-spacing: 0.16em; color: #3a4a5a; font-family: 'IBM Plex Mono', monospace; margin-bottom: 1rem; font-weight: 600; }
.vt-tiers { display: flex; flex-direction: column; gap: 0.5rem; margin-bottom: 1.25rem; }
.vt-tier { display: grid; grid-template-columns: 42px 1fr 52px 70px; gap: 0.75rem; align-items: center; }
.vt-tier-days { font-size: 0.65rem; font-family: 'IBM Plex Mono', monospace; color: #778899; font-weight: 600; }
.vt-tier-bar-wrap { height: 6px; background: rgba(255,215,64,0.06); border-radius: 2px; overflow: hidden; }
.vt-tier-bar { height: 100%; background: linear-gradient(90deg, rgba(255,215,64,0.5), rgba(255,215,64,0.2)); border-radius: 2px; transition: width 0.4s ease; box-shadow: 0 0 6px rgba(255,215,64,0.12); }
.vt-tier-mult { font-size: 0.7rem; font-family: 'IBM Plex Mono', monospace; color: #ffd740; text-align: right; }
.vt-tier-label-text { font-size: 0.62rem; color: #445566; }
.vt-policy-note { font-size: 0.72rem; line-height: 1.65; color: #4a6070; padding: 0.75rem 1rem; border: 1px solid rgba(255,215,64,0.1); background: rgba(255,215,64,0.02); border-left: 2px solid rgba(255,215,64,0.2); }
.vt-policy-tag { font-size: 0.58rem; font-family: 'IBM Plex Mono', monospace; color: #ffd740; border: 1px solid rgba(255,215,64,0.25); padding: 0.15rem 0.5rem; margin-right: 0.5rem; background: rgba(255,215,64,0.05); }

/* ═══ TRANSACTION FEES ═══ */
.fee-eyebrow-tag { font-size: 0.62rem; letter-spacing: 0.2em; font-weight: 600; color: #00e676; font-family: 'IBM Plex Mono', monospace; margin-bottom: 1rem; opacity: 0.75; }
.fee-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 2.5rem; margin: 1.5rem 0 0; }
.fee-formula-label { font-size: 0.52rem; letter-spacing: 0.16em; color: #445566; font-family: 'IBM Plex Mono', monospace; margin-bottom: 0.75rem; }
.fee-formula { font-size: 0.95rem; font-family: 'IBM Plex Mono', monospace; color: #00e676; margin-bottom: 0.5rem; letter-spacing: 0.02em; }
.fee-clamp { font-size: 0.7rem; font-family: 'IBM Plex Mono', monospace; color: #3a5a4a; margin-bottom: 1.25rem; padding-bottom: 0.75rem; border-bottom: 1px solid rgba(0,230,118,0.06); }
.fee-params { display: flex; flex-direction: column; gap: 0.35rem; margin-bottom: 1rem; }
.fee-param { display: grid; grid-template-columns: 90px 110px 1fr; gap: 0.5rem; padding: 0.4rem 0; border-bottom: 1px solid rgba(0,230,118,0.05); align-items: center; }
.fee-plabel { font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem; color: #556677; }
.fee-pval { font-family: 'IBM Plex Mono', monospace; font-size: 0.7rem; color: #00e676; }
.fee-pdesc { font-size: 0.67rem; color: #4a6070; }
.fee-example { font-size: 0.68rem; font-family: 'IBM Plex Mono', monospace; color: #2a5a3a; padding: 0.6rem 0.85rem; border-left: 2px solid rgba(0,230,118,0.2); background: rgba(0,230,118,0.02); box-shadow: -2px 0 8px rgba(0,230,118,0.04); }
.fee-flow-label { font-size: 0.55rem; letter-spacing: 0.16em; color: #3a4a5a; font-family: 'IBM Plex Mono', monospace; margin-bottom: 1rem; font-weight: 600; }
.fee-flow { display: flex; flex-direction: column; align-items: flex-start; gap: 0; }
.fee-flow-step { display: flex; flex-direction: column; align-items: flex-start; width: 100%; }
.fee-flow-node { font-size: 0.72rem; font-family: 'IBM Plex Mono', monospace; padding: 0.55rem 1rem; border: 1px solid rgba(0,230,118,0.1); background: rgba(0,230,118,0.03); color: #7a9a8a; width: 100%; box-sizing: border-box; transition: border-color 0.25s, background 0.25s; }
.fee-flow-node:hover { border-color: rgba(0,230,118,0.2); background: rgba(0,230,118,0.05); }
.fee-node-sender { border-color: rgba(var(--nc-primary-rgb),0.15); color: #6a9aaa; background: rgba(var(--nc-primary-rgb),0.03); }
.fee-node-calc { border-color: rgba(255,215,64,0.12); color: #9a9a6a; background: rgba(255,215,64,0.02); }
.fee-node-receiver { border-color: rgba(0,230,118,0.15); color: #6a9a7a; background: rgba(0,230,118,0.03); }
.fee-node-treasury { border-color: rgba(179,136,255,0.15); color: #9a7abb; background: rgba(179,136,255,0.03); }
.fee-flow-arrow { font-size: 0.7rem; color: #2a3a4a; padding: 0.15rem 1.15rem; }
.fee-exempt { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 1.25rem; align-items: center; }
.fee-exempt-label { font-size: 0.5rem; letter-spacing: 0.14em; color: #2a3a4a; font-family: 'IBM Plex Mono', monospace; font-weight: 600; margin-right: 0.25rem; }
.fee-exempt-item { font-size: 0.62rem; font-family: 'IBM Plex Mono', monospace; color: #3a5060; border: 1px solid rgba(var(--nc-primary-rgb),0.06); padding: 0.2rem 0.55rem; }

/* ═══ ENFORCEMENT ENGINE ═══ */
.enf-eyebrow-tag { font-size: 0.62rem; letter-spacing: 0.2em; font-weight: 600; color: #ff5252; font-family: 'IBM Plex Mono', monospace; margin-bottom: 1rem; opacity: 0.8; }
.enf-layout { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1.5rem; margin: 1.5rem 0 0; }
.enf-block { padding: 1.5rem; background: rgba(6,8,18,0.7); border: 1px solid rgba(100,120,140,0.08); display: flex; flex-direction: column; gap: 0.75rem; box-shadow: 0 2px 12px rgba(0,0,0,0.15); transition: border-color 0.25s, box-shadow 0.25s; }
.enf-block:hover { border-color: rgba(100,120,140,0.16); box-shadow: 0 4px 20px rgba(0,0,0,0.2); }
.enf-block-doom { border-color: rgba(255,82,82,0.12); background: rgba(10,4,6,0.8); }
.enf-block-doom:hover { border-color: rgba(255,82,82,0.22); box-shadow: 0 4px 20px rgba(255,82,82,0.06); }
.enf-block-eyebrow { font-size: 0.55rem; letter-spacing: 0.18em; color: #556677; font-family: 'IBM Plex Mono', monospace; font-weight: 600; }
.enf-eyebrow-red { color: #ff5252; opacity: 0.7; }
.enf-block-title { font-size: 0.95rem; font-weight: 500; color: #c0cad4; }
.enf-block-body { font-size: 0.78rem; line-height: 1.75; color: #556677; margin: 0; }
.enf-bond-conditions { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
/* §LANDINGTRUTH: membership and the commons (replaces the veToken block) */
.mb-status { display: inline-flex; align-items: center; gap: 0.5rem; margin: 0.25rem 0 1.25rem; padding: 0.45rem 0.8rem;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.25); font-family: 'IBM Plex Mono', monospace; font-size: 0.78rem;
  letter-spacing: 0.04em; color: rgba(255, 255, 255, 0.85); }
.mb-status-dot { width: 8px; height: 8px; border-radius: 50%; background: rgba(255, 255, 255, 0.45); flex: 0 0 8px; }
.mb-status-dot--on { background: #4ade80; box-shadow: 0 0 8px rgba(74, 222, 128, 0.6); }
.mb-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.9rem; }
.mb-card { padding: 1rem 1.1rem; background: rgba(var(--nc-primary-rgb), 0.03); border: 1px solid rgba(var(--nc-primary-rgb), 0.1); }
.mb-card-title { margin: 0 0 0.5rem; font-size: 0.9rem; font-weight: 600; color: #e6edf3; display: flex; flex-wrap: wrap;
  align-items: center; gap: 0.5rem; }
.mb-card-body { margin: 0 0 0.5rem; font-size: 0.85rem; line-height: 1.6; color: rgba(255, 255, 255, 0.78); }
.mb-chip { font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem; font-weight: 500; letter-spacing: 0.06em;
  padding: 0.1rem 0.45rem; border: 1px solid rgba(255, 255, 255, 0.3); color: rgba(255, 255, 255, 0.8); }
.mb-chip--on { border-color: rgba(74, 222, 128, 0.5); color: #4ade80; }
.mb-foot { margin: 1rem 0 0; font-size: 0.85rem; color: rgba(255, 255, 255, 0.8); }
.st-links { display: flex; flex-wrap: wrap; gap: 1.25rem; margin: 0.75rem 0 0; font-size: 0.85rem; }
.sdk-a2a-note { max-width: 680px; margin: 1rem auto 0; padding: 0.85rem 1rem; text-align: left; font-size: 0.85rem;
  line-height: 1.65; color: rgba(255, 255, 255, 0.82); background: rgba(var(--nc-primary-rgb), 0.05);
  border-left: 2px solid rgba(var(--nc-primary-rgb), 0.6); }
.sdk-a2a-note-title { display: block; margin-bottom: 0.3rem; color: #e6edf3; }
@media (max-width: 900px) { .mb-grid { grid-template-columns: minmax(0, 1fr); } }
.enf-bond-cond { padding: 0.6rem 0.75rem; background: rgba(var(--nc-primary-rgb),0.03); border: 1px solid rgba(var(--nc-primary-rgb),0.07); }
.enf-bond-val { display: block; font-size: 0.85rem; font-family: 'IBM Plex Mono', monospace; color: var(--nc-primary); font-weight: 300; margin-bottom: 0.2rem; }
.enf-bond-label { display: block; font-size: 0.6rem; letter-spacing: 0.06em; color: #3a5060; }
.enf-ladder { display: flex; flex-direction: column; gap: 0.4rem; }
.enf-rung { padding: 0.6rem 0.75rem; border: 1px solid rgba(100,120,140,0.08); background: rgba(4,6,12,0.5); transition: background 0.25s; }
.enf-rung:hover { background: rgba(4,6,12,0.7); }
.enf-rung-offense { font-size: 0.6rem; font-family: 'IBM Plex Mono', monospace; letter-spacing: 0.1em; margin-bottom: 0.35rem; font-weight: 600; }
.enf-offense-1 { color: #ffd740; opacity: 0.7; }
.enf-offense-2 { color: #ff9100; opacity: 0.8; }
.enf-offense-3 { color: #ff5252; opacity: 0.85; }
.enf-offense-4 { color: #ff1744; }
.enf-rung-actions { display: flex; flex-wrap: wrap; gap: 0.3rem; }
.enf-action { font-size: 0.62rem; font-family: 'IBM Plex Mono', monospace; padding: 0.2rem 0.5rem; border-radius: 1px; }
.enf-action-1 { color: #a07a20; border: 1px solid rgba(255,215,64,0.15); background: rgba(255,215,64,0.04); }
.enf-action-2 { color: #a05020; border: 1px solid rgba(255,145,0,0.2); background: rgba(255,145,0,0.04); }
.enf-action-3 { color: #a02020; border: 1px solid rgba(255,82,82,0.2); background: rgba(255,82,82,0.05); }
.enf-action-4 { color: #cc1020; border: 1px solid rgba(255,23,68,0.25); background: rgba(255,23,68,0.06); }
.enf-ladder-note { font-size: 0.67rem; line-height: 1.6; color: #3a4a5a; font-style: italic; }
.enf-doom-stats { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
.enf-doom-stat { padding: 0.6rem 0.75rem; background: rgba(255,82,82,0.03); border: 1px solid rgba(255,82,82,0.08); }
.enf-doom-val { font-size: 1rem; font-family: 'IBM Plex Mono', monospace; color: #ff5252; font-weight: 300; margin-bottom: 0.2rem; }
.enf-doom-label { font-size: 0.58rem; letter-spacing: 0.06em; color: #3a3040; }

/* ═══ SOVEREIGN OPERATOR SECTION ═══ */
.sec-eyebrow-c { color: #00e676; border-color: rgba(0,230,118,0.2); background: rgba(0,230,118,0.04); }

.op-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 2.5rem; margin-top: 0; }
.op-col-label { font-size: 0.55rem; letter-spacing: 0.18em; color: #3a4a5a; font-family: 'IBM Plex Mono', monospace; font-weight: 600; margin-bottom: 1rem; }

/* Federation Steps */
.op-steps { display: flex; flex-direction: column; gap: 0; margin-bottom: 2rem; }
.op-step { display: flex; gap: 1.25rem; padding: 0.8rem 1rem; border: 1px solid rgba(0,230,118,0.07); border-bottom: none; background: rgba(0,230,118,0.015); transition: background 0.2s, border-left-color 0.25s; border-left: 2px solid rgba(0,230,118,0.07); }
.op-step:first-child { border-radius: 2px 2px 0 0; }
.op-step:last-child { border-bottom: 1px solid rgba(0,230,118,0.07); border-radius: 0 0 2px 2px; }
.op-step:hover { background: rgba(0,230,118,0.03); border-left-color: rgba(0,230,118,0.3); }
.op-step-n { font-size: 0.58rem; font-family: 'IBM Plex Mono', monospace; color: #00e676; opacity: 0.45; flex-shrink: 0; padding-top: 0.18rem; width: 1.5rem; }
.op-step-name { font-size: 0.78rem; font-weight: 500; color: #b0c8b0; margin-bottom: 0.2rem; }
.op-step-desc { font-size: 0.7rem; line-height: 1.6; color: #445566; }

/* Integrity Invariant */
.op-invariant { background: rgba(2,4,10,0.85); border: 1px solid rgba(0,230,118,0.12); padding: 1.25rem 1.5rem; box-shadow: 0 4px 20px rgba(0,0,0,0.2); }
.op-invariant-label { font-size: 0.52rem; letter-spacing: 0.16em; color: #3a5a4a; font-family: 'IBM Plex Mono', monospace; margin-bottom: 0.75rem; font-weight: 600; }
.op-invariant-formula { font-size: 1rem; font-family: 'IBM Plex Mono', monospace; color: #00e676; margin-bottom: 1rem; letter-spacing: 0.02em; padding-bottom: 0.75rem; border-bottom: 1px solid rgba(0,230,118,0.08); }
.op-invariant-steps { display: flex; flex-direction: column; gap: 0.3rem; }
.op-inv-step { display: flex; gap: 0.75rem; align-items: flex-start; }
.op-inv-n { font-size: 0.6rem; font-family: 'IBM Plex Mono', monospace; color: #ff5252; opacity: 0.5; flex-shrink: 0; width: 0.75rem; padding-top: 0.08rem; }
.op-inv-text { font-size: 0.68rem; font-family: 'IBM Plex Mono', monospace; color: #3a4a5a; line-height: 1.6; }

/* Operator Dimensions */
.op-dims { display: grid; grid-template-columns: 1fr 1fr; gap: 0; margin-bottom: 1.5rem; border: 1px solid rgba(var(--nc-primary-rgb),0.06); }
.op-dim { padding: 0.85rem 1rem; border-right: 1px solid rgba(var(--nc-primary-rgb),0.04); border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.04); background: rgba(6,8,18,0.6); transition: background 0.2s, box-shadow 0.25s; }
.op-dim:hover { background: rgba(var(--nc-primary-rgb),0.025); box-shadow: 0 2px 10px rgba(0,0,0,0.12); }
.op-dim:nth-child(even) { border-right: none; }
.op-dim:nth-last-child(-n+2) { border-bottom: none; }
.op-dim-label { font-size: 0.52rem; letter-spacing: 0.12em; color: #3a4a5a; font-family: 'IBM Plex Mono', monospace; margin-bottom: 0.3rem; font-weight: 600; }
.op-dim-val { font-size: 0.82rem; font-family: 'IBM Plex Mono', monospace; color: var(--nc-primary); font-weight: 300; }

/* Sovereignty Card */
.op-sovereignty { border: 1px solid rgba(0,230,118,0.1); background: rgba(4,10,6,0.7); padding: 1.25rem 1.5rem; box-shadow: 0 4px 20px rgba(0,0,0,0.18); transition: border-color 0.25s, box-shadow 0.25s; }
.op-sovereignty:hover { border-color: rgba(0,230,118,0.22); box-shadow: 0 6px 28px rgba(0,0,0,0.22), 0 0 10px rgba(0,230,118,0.04); }
.op-sov-head { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.75rem; }
.op-sov-mark { color: #00e676; font-size: 1rem; opacity: 0.6; }
.op-sov-title { font-size: 0.82rem; font-weight: 500; color: #b0c8b0; }
.op-sov-body { font-size: 0.78rem; line-height: 1.75; color: #4a6050; margin: 0 0 1rem; }
.op-sov-tag-row { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.op-sov-tag { font-size: 0.62rem; font-family: 'IBM Plex Mono', monospace; color: #3a6a4a; border: 1px solid rgba(0,230,118,0.12); padding: 0.22rem 0.6rem; background: rgba(0,230,118,0.03); }

/* ═══ NETWORK CAPACITY BAR ═══ */
.op-capacity-bar { display: flex; justify-content: center; align-items: center; gap: 2.5rem; margin: 2rem 0 2.5rem; padding: 1.5rem 2rem; background: transparent; }
.op-cap-item { text-align: center; }
.op-cap-val { font-family: 'IBM Plex Mono', monospace; font-size: 1.6rem; font-weight: 300; color: #e0e0e0; letter-spacing: -0.02em; }
.op-cap-label { font-size: 0.68rem; color: #445566; margin-top: 0.3rem; letter-spacing: 0.04em; font-family: 'IBM Plex Mono', monospace; }
.op-cap-divider { width: 1px; height: 2rem; background: rgba(255,255,255,0.06); }

/* ═══ APPLY CTA ═══ */
.op-apply-cta { text-align: center; margin: 0 0 3rem; padding: 2.5rem 2rem; position: relative; background: linear-gradient(135deg, rgba(var(--nc-primary-rgb),0.03) 0%, rgba(0,230,118,0.02) 100%); border: 1px solid rgba(var(--nc-primary-rgb),0.08); overflow: hidden; }
.op-apply-cta::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px; background: linear-gradient(90deg, transparent, rgba(var(--nc-primary-rgb),0.3), rgba(0,230,118,0.3), transparent); }
.op-apply-title { font-size: 1.3rem; font-weight: 400; color: #e0e0e0; margin: 0 0 0.6rem; letter-spacing: -0.01em; }
.op-apply-sub { font-size: 0.85rem; color: #78909c; margin: 0 0 1.5rem; font-family: 'IBM Plex Mono', monospace; letter-spacing: 0.02em; }
.op-apply-btn { display: inline-flex; background: transparent; border: 1px solid rgba(var(--nc-primary-rgb),0.25); color: var(--nc-primary); text-decoration: none; cursor: pointer; font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; letter-spacing: 0.12em; padding: 0.75rem 2rem; transition: all 0.3s; }
.op-apply-btn:hover { background: rgba(var(--nc-primary-rgb),0.08); border-color: rgba(var(--nc-primary-rgb),0.5); box-shadow: 0 0 20px rgba(var(--nc-primary-rgb),0.08); }
.op-apply-btn:disabled { opacity: 0.4; cursor: wait; }

/* ═══ OPERATOR APPLICATION FORM ═══ */
.op-apply-form { max-width: 560px; margin: 0 auto; display: flex; flex-direction: column; gap: 0.6rem; box-sizing: border-box; }
.op-apply-form * { box-sizing: border-box; }
.op-form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 0.6rem; }
.op-form-input { background: rgba(6,8,16,0.8); border: 1px solid rgba(var(--nc-primary-rgb),0.1); border-radius: 0; color: #b0bec5; padding: 0.65rem 0.9rem; font-size: 0.82rem; font-family: 'IBM Plex Mono', monospace; outline: none; transition: border-color 0.25s, box-shadow 0.25s; width: 100%; box-sizing: border-box; }
.op-form-input:focus { border-color: rgba(var(--nc-primary-rgb),0.35); box-shadow: 0 0 8px rgba(var(--nc-primary-rgb),0.06); }
.op-form-input::placeholder { color: #2a3a4a; font-family: 'IBM Plex Mono', monospace; }
.op-form-input option { background: #060810; color: #78909c; }
.op-form-textarea { resize: vertical; min-height: 2.5rem; }
select.op-form-input { appearance: none; -webkit-appearance: none; background-image: url("data:image/svg+xml,%3Csvg width='10' height='6' viewBox='0 0 10 6' fill='none' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M1 1l4 4 4-4' stroke='%23445566' stroke-width='1' stroke-linecap='round'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 0.9rem center; padding-right: 2.2rem; }
.op-form-success { text-align: center; color: var(--nc-primary); padding: 1.5rem; }
.op-form-success p { margin: 0.5rem 0 0; color: #78909c; font-family: 'IBM Plex Mono', monospace; font-size: 0.82rem; }

/* ═══ MISSION COMPACT CARD ═══ */
.op-mission-stats { display: flex; justify-content: center; gap: 2.5rem; margin: 18px 0 0; }
.op-mission-stat { text-align: center; }
.op-mission-stat-val { display: block; font-family: 'IBM Plex Mono', monospace; font-size: 1.4rem; font-weight: 700; color: var(--nc-primary); text-shadow: 0 0 12px rgba(var(--nc-primary-rgb),0.2); }
.op-mission-stat-lbl { font-size: 0.72rem; color: #78909c; letter-spacing: 0.02em; }

/* ═══ SHIPS WITH GRID ═══ */
.op-ships-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.75rem 2rem; max-width: 800px; margin: 0 auto; }
.op-ships-item { display: flex; align-items: flex-start; gap: 0.75rem; font-size: 0.9rem; color: #b0bec5; }
.op-ships-check { color: #00e676; font-weight: 600; flex-shrink: 0; margin-top: 0.1rem; }

/* ═══ BETA OPERATOR PROGRAM ═══ */
.op-beta-program { max-width: 800px; margin: 0 auto; }
.op-beta-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; text-align: left; }
.op-beta-col-title { font-size: 0.85rem; font-weight: 500; color: var(--nc-primary); letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 0.75rem; }
.op-beta-list { list-style: none; padding: 0; margin: 0; }
.op-beta-list li { position: relative; padding-left: 1.25rem; margin-bottom: 0.6rem; font-size: 0.88rem; color: #b0bec5; }
.op-beta-list li::before { content: '—'; position: absolute; left: 0; color: var(--nc-primary); }

@media (max-width: 900px) {
  .op-layout { grid-template-columns: 1fr; }
  .op-capacity-bar { flex-direction: column; gap: 1rem; }
  .op-cap-divider { width: 3rem; height: 1px; }
  .op-ships-grid { grid-template-columns: 1fr; }
  .op-beta-cols { grid-template-columns: 1fr; }
  .op-form-row { grid-template-columns: 1fr; }
}

/* ═══ RESPONSIVE ═══ */
@media (max-width: 1024px) {
  .lp-arch-grid { grid-template-columns: repeat(3,1fr); }
  .lp-arch-item:nth-child(3) { border-right: 1px solid rgba(var(--nc-primary-rgb),0.06); }
  .lp-arch-wire { display: none; }
  .lp-detail-grid { grid-template-columns: repeat(2,1fr); }
  .lp-stack-grid { grid-template-columns: repeat(2,1fr); }
}
@media (max-width: 1024px) {
  .enf-layout { grid-template-columns: 1fr 1fr; }
  .vt-layout, .fee-layout { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  .enf-layout { grid-template-columns: 1fr; }
  .mcp-panels { grid-template-columns: 1fr; }
  .mcp-header { flex-direction: column; align-items: flex-start; }
  .mcp-header-stats { gap: 1.5rem; }
  .mcp-h2 { font-size: 1.75rem; }
  .lp-h1 { font-size: 2.2rem; }
  .lp-hero { padding: 5rem 1.5rem 3rem; }
  .lp-arch-grid { grid-template-columns: 1fr 1fr; }
  .lp-detail-grid { grid-template-columns: 1fr; }
  .lp-stack-grid { grid-template-columns: repeat(2,1fr); }
  .lp-hero-actions { flex-direction: column; align-items: flex-start; }
  .lp-hero-stats { gap: 1.5rem; flex-wrap: wrap; }
  .lp-arch-item { border-right: none; }
  .lp-arch-item:nth-child(2n) { border-right: 1px solid rgba(var(--nc-primary-rgb),0.06); }
  .lp-footer-top { flex-direction: column; gap: 1.5rem; }
  .lp-section { padding: 3rem 1.5rem; }
  .lp-beta-card { padding: 2.5rem 1.5rem; }
  /* ZKP flow — stack vertically on mobile */
  .zkp-flow { display: flex; flex-direction: column; gap: 1.5rem; }
  .zkp-flow > * { width: 100%; }
  .zkp-arrow { flex-direction: row; }
  .zkp-arrow-line { width: 60px; height: 2px; }
  .et-layout { grid-template-columns: 1fr; }
}
@media (max-width: 480px) {
  .lp-arch-grid { grid-template-columns: 1fr; }
  .lp-stack-grid { grid-template-columns: 1fr 1fr; }
  .ag-panels { grid-template-columns: 1fr; }
  .zkp-flow { flex-direction: column; }
  .zkp-flow > * { width: 100%; }
  .enf-bond-conditions { grid-template-columns: 1fr; }
  .enf-doom-stats { grid-template-columns: 1fr; }
  .beta-economy { padding: 0.75rem 1rem; }
  .beta-economy-text { font-size: 0.7rem; }
  .lp-container { padding: 0 1rem; overflow-x: hidden; max-width: 100vw; }
  .lp-lead { font-size: 0.85rem; }
  .lp-h1 { font-size: 1.8rem; }
  pre, code { font-size: 0.65rem; overflow-x: auto; }
}

/* ═══ AGENT SHOWCASE ═══ */
.ag {
  padding: 5rem 0;
  border-top: 1px solid rgba(var(--nc-primary-rgb),0.06);
  border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.06);
  background: linear-gradient(180deg, rgba(var(--nc-primary-rgb),0.02) 0%, transparent 100%);
}
.ag-header { text-align: center; margin-bottom: 3rem; }
.ag-eyebrow {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.56rem; font-weight: 600; letter-spacing: 0.25em;
  color: rgba(var(--nc-primary-rgb),0.5); margin-bottom: 1rem;
}
.ag-h2 {
  font-size: clamp(1.6rem, 3.5vw, 2.4rem);
  font-weight: 300; line-height: 1.2;
  color: rgba(255,255,255,0.92); margin-bottom: 1rem;
}
.ag-lead {
  max-width: 680px; margin: 0 auto;
  font-size: 0.88rem; line-height: 1.7;
  color: rgba(255,255,255,0.55);
}
.ag-lead--note {
  margin-top: 0.75rem;
  font-size: 0.8rem;
  color: rgba(255,255,255,0.45);
}
.ag-lead code {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.82rem;
  background: rgba(var(--nc-primary-rgb),0.08);
  padding: 0.15em 0.4em;
  border-radius: 2px;
  color: rgba(var(--nc-primary-rgb),0.8);
}
.ag-panels {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.5rem;
  margin-bottom: 2rem;
}
.ag-panel {
  background: rgba(1,3,8,0.7);
  border: 1px solid rgba(var(--nc-primary-rgb),0.1);
  padding: 2rem;
  position: relative;
  box-shadow: 0 4px 20px rgba(0,0,0,0.2);
  transition: border-color 0.25s, box-shadow 0.25s, transform 0.25s;
}
.ag-panel:hover {
  border-color: rgba(var(--nc-primary-rgb),0.2);
  box-shadow: 0 6px 28px rgba(0,0,0,0.25), 0 0 12px rgba(var(--nc-primary-rgb),0.04);
  transform: translateY(-1px);
}
.ag-panel-live {
  border-color: rgba(var(--nc-primary-rgb),0.2);
  background: linear-gradient(135deg, rgba(var(--nc-primary-rgb),0.04), rgba(1,3,8,0.8));
}
.ag-panel-badge {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.5rem; font-weight: 600; letter-spacing: 0.2em;
  padding: 0.2rem 0.6rem;
  display: inline-block;
  margin-bottom: 1rem;
}
.ag-badge-live {
  background: rgba(0,230,118,0.1);
  border: 1px solid rgba(0,230,118,0.3);
  color: #00e676;
}
.ag-badge-code {
  background: rgba(var(--nc-primary-rgb),0.06);
  border: 1px solid rgba(var(--nc-primary-rgb),0.2);
  color: rgba(var(--nc-primary-rgb),0.7);
}
.ag-panel-title {
  font-size: 1.1rem; font-weight: 500;
  color: rgba(255,255,255,0.9);
  margin-bottom: 0.75rem;
}
.ag-panel-desc {
  font-size: 0.78rem; line-height: 1.65;
  color: rgba(255,255,255,0.45);
  margin-bottom: 1.5rem;
}
.ag-link-cta {
  display: inline-flex; align-items: center; gap: 0.5rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem; font-weight: 600; letter-spacing: 0.18em;
  padding: 0.55rem 1.2rem;
  background: rgba(var(--nc-primary-rgb),0.08);
  border: 1px solid rgba(var(--nc-primary-rgb),0.35);
  color: var(--nc-primary);
  text-decoration: none;
  transition: all 0.25s;
}
.ag-link-cta:hover {
  background: rgba(var(--nc-primary-rgb),0.15);
  border-color: rgba(var(--nc-primary-rgb),0.6);
  box-shadow: 0 0 24px rgba(var(--nc-primary-rgb),0.2);
  transform: translateY(-1px);
}
.ag-url {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem; letter-spacing: 0.08em;
  color: rgba(var(--nc-primary-rgb),0.35);
  margin-top: 1rem;
}

/* Steps */
.ag-steps { display: flex; flex-direction: column; gap: 1.2rem; }
.ag-step { display: flex; gap: 1rem; align-items: flex-start; }
.ag-step-num {
  width: 24px; height: 24px;
  display: flex; align-items: center; justify-content: center;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem; font-weight: 700;
  border: 1px solid rgba(var(--nc-primary-rgb),0.3);
  color: rgba(var(--nc-primary-rgb),0.7);
  flex-shrink: 0;
}
.ag-step-title {
  font-size: 0.78rem; font-weight: 600;
  color: rgba(255,255,255,0.8);
  margin-bottom: 0.25rem;
}
.ag-code {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  background: rgba(var(--nc-primary-rgb),0.06);
  border: 1px solid rgba(var(--nc-primary-rgb),0.12);
  padding: 0.25rem 0.6rem;
  color: rgba(var(--nc-primary-rgb),0.8);
  display: inline-block;
  margin-bottom: 0.3rem;
}
.ag-step-sub {
  font-size: 0.72rem; line-height: 1.5;
  color: rgba(255,255,255,0.4);
}

/* Onboard */
.ag-onboard {
  background: rgba(1,3,8,0.5);
  border: 1px solid rgba(255,215,0,0.12);
  padding: 1.5rem 2rem;
  margin-bottom: 1.5rem;
  box-shadow: 0 4px 20px rgba(0,0,0,0.2);
  transition: border-color 0.25s;
}
.ag-onboard:hover {
  border-color: rgba(255,215,0,0.22);
}
.ag-onboard-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.56rem; font-weight: 600; letter-spacing: 0.2em;
  color: rgba(255,215,0,0.6);
  margin-bottom: 0.6rem;
}
.ag-onboard-desc {
  font-size: 0.78rem; line-height: 1.65;
  color: rgba(255,255,255,0.45);
}
.ag-onboard-desc code {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  background: rgba(255,215,0,0.06);
  padding: 0.1em 0.35em;
  border-radius: 2px;
  color: rgba(255,215,0,0.7);
}

/* ═══ AGENT TRIPTYCH ═══ */
.ag-triptych {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1.25rem;
  margin-bottom: 2rem;
}
@media (max-width: 1200px) {
  .ag-triptych { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 700px) {
  .ag-triptych { grid-template-columns: 1fr; }
}

.ag-agent-card {
  position: relative;
  overflow: hidden;
  border: 1px solid rgba(255,255,255,0.06);
  padding: 0;
  text-decoration: none;
  color: inherit;
  transition: border-color 0.3s, box-shadow 0.3s, transform 0.3s;
  cursor: pointer;
  display: flex;
  flex-direction: column;
}
.ag-agent-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 12px 40px rgba(0,0,0,0.35);
}

.ag-card-glow {
  position: absolute;
  top: -40%;
  left: 50%;
  transform: translateX(-50%);
  width: 200%;
  height: 60%;
  border-radius: 50%;
  pointer-events: none;
  opacity: 0.5;
  transition: opacity 0.3s;
}
.ag-agent-card:hover .ag-card-glow { opacity: 0.8; }
.ag-glow-green  { background: radial-gradient(ellipse, rgba(0,200,83,0.06) 0%, transparent 70%); }
.ag-glow-cyan   { background: radial-gradient(ellipse, rgba(var(--nc-primary-rgb),0.06) 0%, transparent 70%); }
.ag-glow-red    { background: radial-gradient(ellipse, rgba(220,0,60,0.06) 0%, transparent 70%); }
.ag-glow-gold   { background: radial-gradient(ellipse, rgba(201,168,76,0.06) 0%, transparent 70%); }
.ag-glow-amber  { background: radial-gradient(ellipse, rgba(232,220,200,0.05) 0%, transparent 70%); }
.ag-glow-money  { background: radial-gradient(ellipse, rgba(0,255,80,0.06) 0%, transparent 70%); }

.ag-auditor { background: rgba(0,200,83,0.02); border-color: rgba(0,200,83,0.12); }
.ag-auditor:hover { border-color: rgba(0,200,83,0.3); box-shadow: 0 12px 40px rgba(0,0,0,0.35), 0 0 20px rgba(0,200,83,0.06); }
.ag-gerald  { background: rgba(var(--nc-primary-rgb),0.02); border-color: rgba(var(--nc-primary-rgb),0.12); }
.ag-gerald:hover  { border-color: rgba(var(--nc-primary-rgb),0.3); box-shadow: 0 12px 40px rgba(0,0,0,0.35), 0 0 20px rgba(var(--nc-primary-rgb),0.06); }
.ag-sybil   { background: rgba(220,0,60,0.02); border-color: rgba(220,0,60,0.12); }
.ag-sybil:hover   { border-color: rgba(220,0,60,0.3); box-shadow: 0 12px 40px rgba(0,0,0,0.35), 0 0 20px rgba(220,0,60,0.06); }
.ag-boris   { background: rgba(201,168,76,0.02); border-color: rgba(201,168,76,0.12); }
.ag-boris:hover   { border-color: rgba(201,168,76,0.3); box-shadow: 0 12px 40px rgba(0,0,0,0.35), 0 0 20px rgba(201,168,76,0.06); }
.ag-chester { background: rgba(232,220,200,0.02); border-color: rgba(232,220,200,0.10); }
.ag-chester:hover { border-color: rgba(232,220,200,0.25); box-shadow: 0 12px 40px rgba(0,0,0,0.35), 0 0 20px rgba(232,220,200,0.04); }
.ag-gregory { background: rgba(0,255,80,0.02); border-color: rgba(0,255,80,0.12); }
.ag-gregory:hover { border-color: rgba(0,255,80,0.3); box-shadow: 0 12px 40px rgba(0,0,0,0.35), 0 0 20px rgba(0,255,80,0.06); }

.ag-card-content {
  position: relative;
  z-index: 1;
  padding: 1.75rem 1.5rem 1.5rem;
  display: flex;
  flex-direction: column;
  flex: 1;
}

.ag-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.75rem;
}

.ag-card-badge {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.5rem;
  font-weight: 700;
  letter-spacing: 0.2em;
  padding: 0.15rem 0.6rem;
  border: 1px solid;
}
.ag-badge-green { border-color: rgba(0,200,83,0.4); color: rgba(0,200,83,0.8); background: rgba(0,200,83,0.08); }
.ag-badge-cyan  { border-color: rgba(var(--nc-primary-rgb),0.4); color: rgba(var(--nc-primary-rgb),0.8); background: rgba(var(--nc-primary-rgb),0.08); }
.ag-badge-red   { border-color: rgba(220,0,60,0.4); color: rgba(220,0,60,0.8); background: rgba(220,0,60,0.08); }
.ag-badge-gold  { border-color: rgba(201,168,76,0.4); color: rgba(201,168,76,0.8); background: rgba(201,168,76,0.08); }
.ag-badge-amber { border-color: rgba(232,220,200,0.3); color: rgba(232,220,200,0.7); background: rgba(232,220,200,0.06); }
.ag-badge-money { border-color: rgba(0,255,80,0.4); color: rgba(0,255,80,0.8); background: rgba(0,255,80,0.08); }

.ag-card-icon {
  font-size: 1.2rem;
  opacity: 0.6;
}

/* §pass39 (2026-05-18) — Sovereign signature flare in the card header.
   Sits opposite the LIVE pill on the right via flex justify-between.
   FlareEncirclement with size="lg" renders 48px; we bump to 56px for the
   landing-page hero context so the flares POP against the surrounding card. */
.ag-sov-flare {
  flex-shrink: 0;
  margin-left: auto;
}
.ag-sov-flare :deep(.fc-encircle-size-lg) {
  width: 56px;
  height: 56px;
}
@media (max-width: 640px) {
  .ag-sov-flare :deep(.fc-encircle-size-lg) {
    width: 48px;
    height: 48px;
  }
}
.ag-icon-green { color: #00c853; text-shadow: 0 0 8px rgba(0,200,83,0.3); }
.ag-icon-cyan  { color: var(--nc-primary); text-shadow: 0 0 8px rgba(var(--nc-primary-rgb),0.3); }
.ag-icon-red   { color: #dc003c; text-shadow: 0 0 8px rgba(220,0,60,0.3); }
.ag-icon-gold  { color: #c9a84c; text-shadow: 0 0 8px rgba(201,168,76,0.3); }
.ag-icon-amber { color: #e8dcc8; text-shadow: 0 0 8px rgba(232,220,200,0.2); }
.ag-icon-money { color: #00ff50; text-shadow: 0 0 8px rgba(0,255,80,0.3); font-family: 'IBM Plex Mono', monospace; font-weight: 700; }

.ag-card-name {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.95rem;
  font-weight: 700;
  letter-spacing: 0.2em;
  margin-bottom: 0.15rem;
}
.ag-name-green { color: rgba(0,200,83,0.9); }
.ag-name-cyan  { color: rgba(var(--nc-primary-rgb),0.9); }
.ag-name-red   { color: rgba(220,0,60,0.9); }
.ag-name-gold  { color: rgba(201,168,76,0.9); }
.ag-name-amber { color: rgba(232,220,200,0.85); }
.ag-name-money { color: rgba(0,255,80,0.9); }

.ag-card-role {
  font-size: 0.62rem;
  color: rgba(255,255,255,0.3);
  letter-spacing: 0.08em;
  margin-bottom: 1rem;
}

.ag-card-hero {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  margin-bottom: 1rem;
  padding: 0.75rem 0;
  border-top: 1px solid rgba(255,255,255,0.04);
  border-bottom: 1px solid rgba(255,255,255,0.04);
}

.ag-hero-delta {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 2.2rem;
  font-weight: 200;
  line-height: 1;
}
.ag-hero-green .ag-hero-delta { color: #00c853; text-shadow: 0 0 20px rgba(0,200,83,0.2); }
.ag-hero-cyan  .ag-hero-delta { color: var(--nc-primary); text-shadow: 0 0 20px rgba(var(--nc-primary-rgb),0.2); }
.ag-hero-red   .ag-hero-delta { color: #dc003c; text-shadow: 0 0 20px rgba(220,0,60,0.2); }
.ag-hero-gold  .ag-hero-delta { color: #c9a84c; text-shadow: 0 0 20px rgba(201,168,76,0.2); }
.ag-hero-amber .ag-hero-delta { color: #e8dcc8; text-shadow: 0 0 20px rgba(232,220,200,0.15); }
.ag-hero-money .ag-hero-delta { color: #00ff50; text-shadow: 0 0 20px rgba(0,255,80,0.2); }

.ag-hero-unit {
  font-size: 0.6rem;
  color: rgba(255,255,255,0.25);
  letter-spacing: 0.06em;
}

.ag-card-desc {
  font-size: 0.72rem;
  line-height: 1.65;
  color: rgba(255,255,255,0.4);
  margin-bottom: 1rem;
  flex: 1;
}
.ag-card-desc code {
  font-size: 0.65rem;
  color: rgba(255,255,255,0.5);
  background: rgba(255,255,255,0.04);
  padding: 0.1rem 0.3rem;
}

.ag-card-stats {
  display: flex;
  gap: 1rem;
  margin-bottom: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid rgba(255,255,255,0.04);
}

.ag-card-stat {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.ag-stat-val {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.8rem;
  font-weight: 600;
  color: rgba(255,255,255,0.7);
}
.ag-val-green { color: rgba(0,200,83,0.9); }
.ag-val-cyan  { color: rgba(var(--nc-primary-rgb),0.9); }
.ag-val-red   { color: rgba(220,0,60,0.9); }
.ag-val-gold  { color: rgba(201,168,76,0.9); }
.ag-val-amber { color: rgba(232,220,200,0.8); }
.ag-val-money { color: rgba(0,255,80,0.9); }

.ag-stat-label {
  font-size: 0.5rem;
  color: rgba(255,255,255,0.2);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.ag-card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  margin-bottom: 0.75rem;
}

.ag-card-did {
  margin-top: auto;
}
.ag-card-did code {
  font-size: 0.58rem;
  color: rgba(255,255,255,0.2);
  letter-spacing: 0.04em;
}
.ag-agent-card:hover .ag-card-did code {
  color: rgba(255,255,255,0.4);
}

/* ═══ DOWNLOAD SECTION ═══ */
.ag-download-section {
  margin-bottom: 1rem;
}

.ag-download-card {
  background: rgba(0, 200, 83, 0.02);
  border: 1px solid rgba(0, 200, 83, 0.12);
  padding: 2rem 2.5rem;
  transition: border-color 0.3s;
}
.ag-download-card:hover {
  border-color: rgba(0, 200, 83, 0.25);
}

.ag-download-header {
  margin-bottom: 1.5rem;
}

.ag-download-badge {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.5rem; font-weight: 700; letter-spacing: 0.2em;
  color: rgba(0, 200, 83, 0.8);
  margin-bottom: 0.5rem;
}

.ag-download-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 1.1rem; font-weight: 700; letter-spacing: 0.08em;
  color: rgba(255,255,255,0.85);
  margin: 0 0 0.75rem;
}

.ag-download-lead {
  font-size: 0.78rem; line-height: 1.65;
  color: rgba(255,255,255,0.45);
  max-width: 600px;
}
.ag-download-lead strong { color: rgba(0, 200, 83, 0.9); }

.ag-download-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1rem;
  margin-bottom: 1.5rem;
  padding: 1rem 0;
  border-top: 1px solid rgba(255,255,255,0.04);
  border-bottom: 1px solid rgba(255,255,255,0.04);
}

.ag-download-stat {
  text-align: center;
}

.ag-dl-num {
  display: block;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 1.4rem; font-weight: 200;
  color: rgba(0, 200, 83, 0.85);
  line-height: 1.2;
  margin-bottom: 0.2rem;
}

.ag-dl-label {
  font-size: 0.55rem;
  color: rgba(255,255,255,0.25);
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.ag-download-steps {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  margin-bottom: 1rem;
}

.ag-dl-step {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.ag-dl-step-num {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem; font-weight: 700;
  color: rgba(0, 200, 83, 0.7);
  width: 20px; height: 20px;
  display: flex; align-items: center; justify-content: center;
  border: 1px solid rgba(0, 200, 83, 0.25);
  border-radius: 50%;
  flex-shrink: 0;
}

.ag-dl-step-text {
  font-size: 0.72rem;
  color: rgba(255,255,255,0.5);
}
.ag-dl-step-text code {
  color: rgba(0, 200, 83, 0.7);
  font-size: 0.65rem;
  background: rgba(0, 200, 83, 0.04);
  padding: 0.1rem 0.3rem;
}

.ag-dl-link {
  color: rgba(0, 200, 83, 0.8);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.ag-download-note {
  font-size: 0.65rem;
  color: rgba(255,255,255,0.25);
  margin: 0;
}
.ag-download-note code {
  color: rgba(var(--nc-primary-rgb), 0.5);
  font-size: 0.6rem;
}

@media (max-width: 640px) {
  .ag-download-grid { grid-template-columns: repeat(2, 1fr); }
  .ag-download-card { padding: 1.5rem; }
}

/* Deploy row (legacy) */
.ag-deploy-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.25rem;
  margin-bottom: 1rem;
}
@media (max-width: 768px) { .ag-deploy-row { grid-template-columns: 1fr; } }

.ag-deploy-card {
  background: rgba(255,255,255,0.015);
  border: 1px solid rgba(255,255,255,0.06);
  padding: 1.5rem 1.75rem;
}

.ag-deploy-badge {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.48rem; font-weight: 600; letter-spacing: 0.2em;
  color: rgba(var(--nc-primary-rgb),0.6);
  margin-bottom: 0.5rem;
}

.ag-deploy-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.85rem; font-weight: 600; letter-spacing: 0.1em;
  color: rgba(255,255,255,0.7);
  margin: 0 0 0.75rem;
}

.ag-deploy-desc {
  font-size: 0.72rem; line-height: 1.65;
  color: rgba(255,255,255,0.4);
  margin: 0;
}
.ag-deploy-desc code {
  font-size: 0.65rem; color: rgba(var(--nc-primary-rgb),0.6);
  background: rgba(var(--nc-primary-rgb),0.04); padding: 0.1rem 0.3rem;
}

/* SYBIL algorithm tags — reused from cards */
.ag-tag {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.45rem; font-weight: 600; letter-spacing: 0.15em;
  padding: 0.12rem 0.4rem;
  border: 1px solid;
  transition: box-shadow 0.25s;
}
.ag-tag-cobra   { border-color: rgba(220,0,60,0.35);   color: rgba(220,0,60,0.65); }
.ag-tag-cobra:hover { box-shadow: 0 0 6px rgba(220,0,60,0.12); }
.ag-tag-hydra   { border-color: rgba(0,180,220,0.35);  color: rgba(0,180,220,0.65); }
.ag-tag-hydra:hover { box-shadow: 0 0 6px rgba(0,180,220,0.12); }
.ag-tag-viper   { border-color: rgba(0,220,80,0.35);   color: rgba(0,220,80,0.65); }
.ag-tag-viper:hover { box-shadow: 0 0 6px rgba(0,220,80,0.12); }
.ag-tag-leech   { border-color: rgba(255,160,0,0.35);  color: rgba(255,160,0,0.65); }
.ag-tag-leech:hover { box-shadow: 0 0 6px rgba(255,160,0,0.12); }
.ag-tag-wraith  { border-color: rgba(160,0,255,0.35);  color: rgba(160,0,255,0.65); }
.ag-tag-wraith:hover { box-shadow: 0 0 6px rgba(160,0,255,0.12); }
.ag-tag-phantom { border-color: rgba(160,0,255,0.35);  color: rgba(160,0,255,0.65); }
.ag-tag-phantom:hover { box-shadow: 0 0 6px rgba(160,0,255,0.12); }
.ag-tag-phantom { border-color: rgba(160,0,255,0.4);  color: rgba(160,0,255,0.7); }
.ag-tag-phantom:hover { box-shadow: 0 0 8px rgba(160,0,255,0.15); }

/* ═══ SDK SECTION ═══ */
.sdk { padding: 5rem 0; position: relative; overflow: hidden; background: radial-gradient(ellipse 80% 50% at 50% 20%, rgba(var(--nc-primary-rgb),0.015) 0%, transparent 70%); }
.sdk::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px; background: linear-gradient(90deg, transparent 0%, rgba(245,180,30,0.2) 50%, transparent 100%); }

.sdk-header { text-align: center; margin-bottom: 2.5rem; }
.sdk-badge-row { display: flex; justify-content: center; gap: 0.5rem; margin-bottom: 1rem; }
.sdk-badge {
  display: inline-block; padding: 0.25rem 0.7rem; border-radius: 4px;
  font-size: 0.5rem; font-weight: 800; letter-spacing: 0.15em;
  background: rgba(245,180,30,0.1); border: 1px solid rgba(245,180,30,0.3);
  color: rgba(245,180,30,0.9); font-family: 'Fira Code', monospace;
}
.sdk-badge-ver { background: rgba(var(--nc-primary-rgb),0.06); border-color: rgba(var(--nc-primary-rgb),0.2); color: rgba(var(--nc-primary-rgb),0.7); }
.sdk-h2 {
  font-size: 2.5rem; font-weight: 200; letter-spacing: 0.08em;
  background: linear-gradient(135deg, rgba(245,180,30,0.9) 0%, rgba(var(--nc-primary-rgb),0.9) 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text; margin-bottom: 0.3rem;
}
.sdk-tagline { font-size: 0.7rem; letter-spacing: 0.2em; color: rgba(255,255,255,0.2); margin-bottom: 1rem; text-transform: uppercase; }
.sdk-lead { font-size: 0.85rem; color: rgba(255,255,255,0.35); max-width: 600px; margin: 0 auto; line-height: 1.7; }

.sdk-install {
  text-align: center; margin: 2rem 0;
}
.sdk-install-cmd {
  display: inline-block; padding: 0.6rem 1.5rem; border-radius: 6px;
  background: rgba(0,0,0,0.4); border: 1px solid rgba(245,180,30,0.15);
  font-family: 'Fira Code', monospace; font-size: 0.85rem;
  color: rgba(245,180,30,0.8); letter-spacing: 0.03em;
}

/* Bridge cards */
.sdk-bridges { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 1rem; margin-bottom: 2.5rem; }
.sdk-bridge {
  padding: 1.2rem; border-radius: 8px;
  background: rgba(10,14,20,0.6); border: 1px solid rgba(255,255,255,0.04);
  transition: all 0.3s;
}
.sdk-bridge:hover { border-color: rgba(245,180,30,0.15); transform: translateY(-2px); box-shadow: 0 8px 30px rgba(0,0,0,0.3); }
.sdk-bridge-top { display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.6rem; }
.sdk-bridge-icon { font-size: 1.2rem; color: rgba(245,180,30,0.7); flex-shrink: 0; }
.sdk-bridge-name { font-size: 0.85rem; font-weight: 700; color: rgba(255,255,255,0.7); letter-spacing: 0.05em; }
.sdk-bridge-by { font-size: 0.5rem; color: rgba(255,255,255,0.2); }
.sdk-bridge-tests {
  margin-left: auto; font-size: 0.45rem; font-weight: 700;
  padding: 0.15rem 0.4rem; border-radius: 3px;
  background: rgba(16,220,129,0.08); color: rgba(16,220,129,0.7);
  font-family: 'Fira Code', monospace; letter-spacing: 0.05em; flex-shrink: 0;
}
.sdk-bridge-desc { font-size: 0.65rem; color: rgba(255,255,255,0.25); line-height: 1.5; margin-bottom: 0.6rem; }
.sdk-bridge-features { display: flex; flex-wrap: wrap; gap: 0.3rem; }
.sdk-bridge-feat {
  font-size: 0.4rem; padding: 0.1rem 0.35rem; border-radius: 3px;
  border: 1px solid rgba(var(--nc-primary-rgb),0.1); color: rgba(var(--nc-primary-rgb),0.5);
  font-family: 'Fira Code', monospace; letter-spacing: 0.03em;
}

/* Code example */
.sdk-code-section { margin-bottom: 2.5rem; max-width: 650px; margin-left: auto; margin-right: auto; }
.sdk-code-tabs { display: flex; gap: 0; margin-bottom: 0; flex-wrap: wrap; }
@media (max-width: 480px) {
  .sdk-code-tab { padding: 0.35rem 0.55rem; font-size: 0.46rem; }
}
.sdk-code-tab {
  padding: 0.4rem 0.8rem; font-size: 0.5rem; font-weight: 600;
  color: rgba(255,255,255,0.2); border: 1px solid rgba(255,255,255,0.04);
  border-bottom: none; border-radius: 4px 4px 0 0; cursor: pointer;
  letter-spacing: 0.05em; font-family: 'Fira Code', monospace;
}
.sdk-code-tab-active { color: rgba(245,180,30,0.7); background: rgba(0,0,0,0.4); border-color: rgba(245,180,30,0.1); }
.sdk-code {
  padding: 1.2rem 1.5rem; border-radius: 0 6px 6px 6px;
  background: rgba(0,0,0,0.4); border: 1px solid rgba(245,180,30,0.08);
  font-family: 'Fira Code', monospace; font-size: 0.7rem; line-height: 1.7;
  color: rgba(255,255,255,0.5); overflow-x: auto; white-space: pre;
}
.sdk-kw { color: rgba(198,120,221,0.8); }
.sdk-cls { color: rgba(245,180,30,0.9); }
.sdk-fn { color: rgba(97,175,239,0.9); }
.sdk-str { color: rgba(152,195,121,0.8); }
.sdk-cmt { color: rgba(255,255,255,0.15); }

/* Stats */
.sdk-stats {
  display: flex; justify-content: center; gap: 3rem; margin-bottom: 2.5rem;
  padding: 1.5rem 0; border-top: 1px solid rgba(255,255,255,0.03); border-bottom: 1px solid rgba(255,255,255,0.03);
}
.sdk-stat { display: flex; flex-direction: column; align-items: center; }
.sdk-stat-val {
  font-size: 1.8rem; font-weight: 200; letter-spacing: 0.05em;
  background: linear-gradient(135deg, rgba(245,180,30,0.9), rgba(var(--nc-primary-rgb),0.9));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text; font-family: 'Fira Code', monospace;
}
.sdk-stat-label { font-size: 0.4rem; letter-spacing: 0.2em; color: rgba(255,255,255,0.15); font-weight: 700; margin-top: 0.3rem; }

/* Identity section */
.sdk-identity {
  max-width: 600px; margin: 0 auto; text-align: center;
  padding: 1.5rem; border-radius: 8px;
  background: rgba(10,14,20,0.6); border: 1px solid rgba(245,180,30,0.06);
}
.sdk-identity-title { font-size: 0.45rem; letter-spacing: 0.2em; color: rgba(245,180,30,0.4); font-weight: 700; margin-bottom: 1rem; }
.sdk-identity-flow { display: flex; flex-direction: column; align-items: center; gap: 0.35rem; margin-bottom: 1rem; }
.sdk-did { overflow-wrap: anywhere; max-width: 100%; text-align: center;
  padding: 0.4rem 0.8rem; border-radius: 4px;
  font-family: 'Fira Code', monospace; font-size: 0.6rem; font-weight: 600;
}
.sdk-did-cos { background: rgba(var(--nc-primary-rgb),0.08); border: 1px solid rgba(var(--nc-primary-rgb),0.2); color: rgba(var(--nc-primary-rgb),0.8); }
.sdk-did-wba { background: rgba(245,180,30,0.08); border: 1px solid rgba(245,180,30,0.2); color: rgba(245,180,30,0.8); }
.sdk-identity-arrow { font-size: 1.2rem; line-height: 1; color: rgba(255,255,255,0.45); }
.sdk-identity-desc { font-size: 0.65rem; color: rgba(255,255,255,0.2); line-height: 1.6; }

@media (max-width: 768px) {
  .sdk-h2 { font-size: 1.8rem; }
  .sdk-bridges { grid-template-columns: 1fr; }
  .sdk-stats { gap: 1.5rem; flex-wrap: wrap; }
  .sdk-identity-flow { flex-direction: column; }
}

/* ═══════════════════════════════════════════
   PROTOCOL THEATRE TEASER
   ═══════════════════════════════════════════ */

.pt-teaser {
  position: relative;
  z-index: 1;
  padding: 6rem 2rem;
  background: radial-gradient(ellipse 70% 50% at 50% 30%, rgba(16,185,129,0.03) 0%, transparent 50%),
              radial-gradient(ellipse 70% 50% at 50% 70%, rgba(139,92,246,0.03) 0%, transparent 50%);
}

.pt-stage {
  position: relative;
  max-width: 800px;
  margin: 0 auto;
  padding: 3rem 2.5rem;
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.015);
  backdrop-filter: blur(8px);
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  overflow: hidden;
}

.pt-stage-glow {
  position: absolute;
  inset: -60px;
  background: radial-gradient(ellipse at 30% 40%, rgba(16,185,129,0.08) 0%, transparent 50%),
              radial-gradient(ellipse at 70% 60%, rgba(139,92,246,0.08) 0%, transparent 50%);
  pointer-events: none;
}

.pt-eyebrow {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 2px;
  color: #64748b;
  text-transform: uppercase;
  margin-bottom: 2.5rem;
}
.pt-eyebrow-icon {
  color: #10b981;
  font-size: 10px;
}

/* ── Exchange visualization ── */

.pt-exchange {
  display: flex;
  align-items: center;
  gap: 0;
  width: 100%;
  max-width: 680px;
  margin-bottom: 2.5rem;
}

.pt-node {
  flex: 0 0 100px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.pt-node-ring {
  width: 64px;
  height: 64px;
}
.pt-node-ring svg {
  width: 100%;
  height: 100%;
}

.pt-node-name {
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 1.5px;
}
.pt-gerald .pt-node-name { color: #10b981; }
.pt-sybil .pt-node-name { color: #8b5cf6; }

.pt-node-role {
  font-size: 0.6rem;
  color: #64748b;
  letter-spacing: 0.5px;
}

/* ── Arrows ── */

.pt-arrows {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 0 12px;
  min-width: 0;
}

.pt-arrow {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.pt-arrow-line {
  width: 100%;
  height: 2px;
  border-radius: 1px;
  position: relative;
  overflow: hidden;
}
.pt-arrow-ltr .pt-arrow-line {
  background: linear-gradient(90deg, #10b981 0%, rgba(16,185,129,0.2) 100%);
}
.pt-arrow-rtl .pt-arrow-line {
  background: linear-gradient(270deg, #8b5cf6 0%, rgba(139,92,246,0.2) 100%);
}
.pt-arrow-payment .pt-arrow-line {
  background: linear-gradient(90deg, #f59e0b 0%, rgba(245,158,11,0.2) 100%);
}

.pt-arrow-pulse {
  position: absolute;
  top: -1px;
  width: 24px;
  height: 4px;
  border-radius: 2px;
  background: rgba(16,185,129,0.9);
  box-shadow: 0 0 12px rgba(16,185,129,0.6);
  animation: pulseLTR 3s ease-in-out infinite;
}
.pt-arrow-rtl .pt-arrow-pulse {
  background: rgba(139,92,246,0.9);
  box-shadow: 0 0 12px rgba(139,92,246,0.6);
  animation: pulseRTL 3s ease-in-out infinite;
  animation-delay: 1s;
}
.pt-pulse-gold {
  background: rgba(245,158,11,0.9) !important;
  box-shadow: 0 0 12px rgba(245,158,11,0.6) !important;
  animation-delay: 2s !important;
}

@keyframes pulseLTR {
  0% { left: -24px; opacity: 0; }
  10% { opacity: 1; }
  90% { opacity: 1; }
  100% { left: calc(100% + 24px); opacity: 0; }
}
@keyframes pulseRTL {
  0% { right: -24px; left: auto; opacity: 0; }
  10% { opacity: 1; }
  90% { opacity: 1; }
  100% { right: calc(100% + 24px); left: auto; opacity: 0; }
}

.pt-arrow-label {
  font-size: 0.65rem;
  font-weight: 700;
  font-family: 'SF Mono', 'Fira Code', monospace;
  letter-spacing: 0.5px;
  padding: 1px 6px;
  border-radius: 3px;
}
.pt-label-gerald {
  color: #10b981;
  background: rgba(16,185,129,0.08);
}
.pt-label-sybil {
  color: #8b5cf6;
  background: rgba(139,92,246,0.08);
}
.pt-label-payment {
  color: #f59e0b;
  background: rgba(245,158,11,0.08);
}

.pt-arrow-sub {
  font-size: 0.58rem;
  color: #475569;
  font-family: monospace;
}

/* ── Copy + CTA ── */

.pt-headline {
  font-size: 1.6rem;
  font-weight: 700;
  line-height: 1.3;
  color: #e2e8f0;
  margin: 0 0 1rem;
}

.pt-description {
  font-size: 0.88rem;
  color: #94a3b8;
  line-height: 1.6;
  max-width: 560px;
  margin: 0 0 2rem;
}

.pt-cta {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 14px 32px;
  font-size: 0.82rem;
  font-weight: 700;
  letter-spacing: 1.5px;
  color: #0a0a0f;
  background: linear-gradient(135deg, #10b981, #34d399);
  border: none;
  border-radius: 8px;
  text-decoration: none;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 4px 20px rgba(16,185,129,0.25), 0 0 40px rgba(16,185,129,0.1);
}
.pt-cta:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 28px rgba(16,185,129,0.35), 0 0 60px rgba(16,185,129,0.15);
}

.pt-stats-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 1.8rem;
  flex-wrap: wrap;
  justify-content: center;
}
.pt-stat {
  font-size: 0.68rem;
  color: #64748b;
  letter-spacing: 0.3px;
}
.pt-stat-val {
  color: #94a3b8;
  font-weight: 600;
  font-family: 'SF Mono', 'Fira Code', monospace;
}
.pt-stat-sep {
  color: #334155;
  font-size: 0.7rem;
}
.pt-blog-link {
  display: inline-block;
  margin-top: 1.1rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  letter-spacing: 0.04em;
  color: #8b5cf6;
  text-decoration: none;
  border-bottom: 1px dotted rgba(139,92,246,0.4);
  transition: all 0.2s;
}
.pt-blog-link:hover {
  color: #a78bfa;
  border-bottom-color: rgba(167,139,250,0.7);
}

@media (max-width: 768px) {
  .pt-teaser { padding: 3rem 1rem; }
  .pt-stage { padding: 2rem 1.5rem; }
  .pt-exchange { flex-direction: column; gap: 20px; }
  .pt-arrows { flex-direction: column; padding: 0; }
  .pt-node { flex: none; }
  .pt-headline { font-size: 1.3rem; }
  .pt-stats-row { gap: 6px; }
}

/* ═══════════════════════════════════════════
   AVT SUPPLY POLICY SECTION
   ═══════════════════════════════════════════ */

.sp-section {
  position: relative;
  z-index: 1;
  padding: 6rem 2rem;
  background: radial-gradient(ellipse 80% 50% at 50% 20%, rgba(16, 185, 129, 0.025) 0%, transparent 60%),
              radial-gradient(ellipse 60% 40% at 50% 80%, rgba(var(--nc-primary-rgb), 0.02) 0%, transparent 50%);
}

.sp-stage {
  position: relative;
  max-width: 1000px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.sp-stage-glow {
  position: absolute;
  inset: -80px;
  background: radial-gradient(ellipse at 50% 30%, rgba(16, 185, 129, 0.04) 0%, transparent 60%);
  pointer-events: none;
}

.sp-eyebrow {
  font-size: 0.6rem;
  font-weight: 600;
  letter-spacing: 0.22em;
  color: #10b981;
  border: 1px solid rgba(16, 185, 129, 0.2);
  padding: 0.25rem 0.75rem;
  margin-bottom: 2rem;
  font-family: 'IBM Plex Mono', monospace;
  background: rgba(16, 185, 129, 0.04);
  box-shadow: 0 0 10px rgba(16, 185, 129, 0.06);
  display: inline-block;
}

.sp-title {
  font-size: 2rem;
  font-weight: 300;
  color: #e0e6ed;
  letter-spacing: 0.01em;
  margin-bottom: 1rem;
  text-shadow: 0 0 40px rgba(var(--nc-primary-rgb), 0.08);
}

.sp-subtitle {
  font-size: 0.95rem;
  line-height: 1.8;
  color: #6a7a8a;
  max-width: 640px;
  margin-bottom: 3rem;
}

.sp-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1px;
  width: 100%;
  margin-bottom: 3rem;
  background: rgba(16, 185, 129, 0.08);
  border: 1px solid rgba(16, 185, 129, 0.08);
  border-radius: 4px;
  overflow: hidden;
}

.sp-card {
  background: rgba(6, 10, 16, 0.92);
  padding: 2rem 1.5rem;
  text-align: left;
  position: relative;
  transition: background 0.25s;
}
.sp-card:hover {
  background: rgba(10, 16, 24, 0.95);
}

.sp-card-num {
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.15em;
  color: #10b981;
  opacity: 0.5;
  margin-bottom: 0.75rem;
  font-family: 'IBM Plex Mono', 'SF Mono', monospace;
}

.sp-card-title {
  font-size: 1rem;
  font-weight: 600;
  color: #c8d6e5;
  margin-bottom: 0.6rem;
  letter-spacing: 0.01em;
}

.sp-card-text {
  font-size: 0.85rem;
  line-height: 1.7;
  color: #667788;
}
.sp-card-text code {
  font-family: 'IBM Plex Mono', 'SF Mono', monospace;
  font-size: 0.78rem;
  color: #10b981;
  background: rgba(16, 185, 129, 0.08);
  padding: 0.1em 0.35em;
  border-radius: 2px;
}

.sp-bottom-line {
  font-size: 1rem;
  font-weight: 600;
  color: #c8d6e5;
  max-width: 700px;
  line-height: 1.6;
  margin-bottom: 2.5rem;
  padding: 1.25rem 2rem;
  border-left: 3px solid #10b981;
  background: rgba(16, 185, 129, 0.04);
  text-align: left;
}

.sp-stats-row {
  display: flex;
  justify-content: center;
  gap: 3rem;
  margin-bottom: 2rem;
  flex-wrap: wrap;
}

.sp-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.25rem;
}

.sp-stat-val {
  font-size: 1.5rem;
  font-weight: 300;
  color: #e0e6ed;
  font-family: 'IBM Plex Mono', 'SF Mono', monospace;
}

.sp-stat-label {
  font-size: 0.65rem;
  font-weight: 600;
  letter-spacing: 0.15em;
  color: #556677;
  text-transform: uppercase;
}

.sp-audit-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.12em;
  color: #10b981;
  text-decoration: none;
  padding: 0.6rem 1.5rem;
  border: 1px solid rgba(16, 185, 129, 0.25);
  background: rgba(16, 185, 129, 0.04);
  transition: all 0.2s;
}
.sp-audit-link:hover {
  background: rgba(16, 185, 129, 0.1);
  border-color: rgba(16, 185, 129, 0.4);
  box-shadow: 0 0 20px rgba(16, 185, 129, 0.12);
}

@media (max-width: 768px) {
  .sp-section { padding: 3rem 1rem; }
  .sp-grid { grid-template-columns: 1fr; }
  .sp-title { font-size: 1.5rem; }
  .sp-stats-row { gap: 1.5rem; }
  .sp-bottom-line { padding: 1rem 1.25rem; font-size: 0.9rem; }
}

/* ═══ INLINE DOC LINKS ═══ */
.lp-inline-link { color: var(--nc-primary); text-decoration: none; transition: color 0.15s; }
.lp-inline-link:hover { color: #4aeaea; text-decoration: underline; }

/* ═══ ISO 42001 COMPLIANCE BANNER ═══ */
.iso-banner {
  position: relative;
  background: linear-gradient(135deg, rgba(var(--nc-primary-rgb),0.04) 0%, rgba(0,230,118,0.02) 50%, rgba(var(--nc-primary-rgb),0.04) 100%);
  border: 1px solid rgba(var(--nc-primary-rgb),0.12);
  border-radius: 16px;
  padding: 32px 36px;
  overflow: hidden;
}
.iso-banner-glow {
  position: absolute;
  top: -40px;
  right: -40px;
  width: 200px;
  height: 200px;
  background: radial-gradient(circle, rgba(var(--nc-primary-rgb),0.08) 0%, transparent 70%);
  pointer-events: none;
}
.iso-banner-content {
  position: relative;
  display: flex;
  align-items: center;
  gap: 28px;
}
.iso-badge {
  flex-shrink: 0;
}
.iso-badge-ring {
  position: relative;
  width: 40px;
  height: 40px;
}
.iso-badge-arc {
  animation: iso-spin 8s linear infinite;
  transform-origin: center;
}
@keyframes iso-spin { to { transform: rotate(360deg); } }
.iso-badge-pct {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  font-weight: 700;
  color: var(--nc-primary);
}
.iso-text { flex: 1; min-width: 0; }
.iso-eyebrow {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.18em;
  color: rgba(var(--nc-primary-rgb),0.6);
  margin-bottom: 6px;
}
.iso-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: #fff;
  margin: 0 0 6px;
  letter-spacing: -0.01em;
}
.iso-desc {
  font-size: 0.82rem;
  color: #78909c;
  line-height: 1.6;
  margin: 0;
}
.iso-cta {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  background: rgba(var(--nc-primary-rgb),0.06);
  border: 1px solid rgba(var(--nc-primary-rgb),0.25);
  border-radius: 8px;
  color: var(--nc-primary);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-decoration: none;
  white-space: nowrap;
  transition: all 0.2s;
  flex-shrink: 0;
}
.iso-cta:hover {
  background: rgba(var(--nc-primary-rgb),0.12);
  border-color: rgba(var(--nc-primary-rgb),0.45);
  box-shadow: 0 0 16px rgba(var(--nc-primary-rgb),0.1);
}
.iso-docs-note {
  font-size: 0.72rem;
  color: #5b6f7d;
  font-style: italic;
  margin: 6px 0 0;
}
@media (max-width: 768px) {
  .iso-banner-content { flex-direction: column; text-align: center; gap: 16px; }
  .iso-banner { padding: 24px 20px; }
}

/* ═══ GCC TEASER ═══ */
.gcc-teaser-stage {
  margin: 2rem auto 0;
  max-width: 920px;
}
.gcc-teaser-video {
  display: block;
  width: 100%;
  border-radius: 12px;
  border: 1px solid rgba(var(--nc-primary-rgb),0.25);
  background: #04070c;
  box-shadow: 0 10px 50px rgba(0,0,0,0.55), 0 0 30px rgba(var(--nc-primary-rgb),0.08);
}
.gcc-teaser-caption {
  margin-top: 0.7rem;
  text-align: center;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem;
  letter-spacing: 0.05em;
  color: #5b6f7d;
}
.gcc-teaser-ctas {
  display: flex;
  justify-content: center;
  gap: 14px;
  margin-top: 1.6rem;
  flex-wrap: wrap;
}
.gcc-teaser-cta {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.14);
  border-radius: 8px;
  color: #aab8c5;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-decoration: none;
  transition: all 0.2s;
}
.gcc-teaser-cta:hover {
  border-color: rgba(255,255,255,0.3);
  color: #e2e8f0;
}
.gcc-teaser-cta-primary {
  background: rgba(var(--nc-primary-rgb),0.06);
  border-color: rgba(var(--nc-primary-rgb),0.25);
  color: var(--nc-primary);
}
.gcc-teaser-cta-primary:hover {
  background: rgba(var(--nc-primary-rgb),0.12);
  border-color: rgba(var(--nc-primary-rgb),0.45);
  color: var(--nc-primary);
  box-shadow: 0 0 16px rgba(var(--nc-primary-rgb),0.1);
}

/* ═══════════════════════════════════════════════════════════════ */
/* MOBILE OPTIMIZATION — comprehensive, no desktop regressions    */
/* ═══════════════════════════════════════════════════════════════ */

/* NAV: legacy compact-row rules are superseded by the §27 hamburger
   drawer at <1024px. The new rules above cover everything (padding,
   font-size, display:flex column, etc.). Leaving these as no-ops to
   avoid breaking layout if some other rule depends on them — but
   crucially NOT hiding lp-link-blue / lp-link-purple anymore, since
   they're visible inside the drawer. */
@media (max-width: 768px) {
  .lp-nav-inner { padding: 0.65rem 1rem; }
  .lp-brand span { font-size: 0.85rem; letter-spacing: 0.18em; }
}

/* HERO: responsive text + padding */
@media (max-width: 768px) {
  .lp-hero { min-height: 85vh; overflow-x: clip; }
  .lp-hero-inner {
    padding: 5rem 1rem 3rem 1rem !important; max-width: 100% !important;
    text-align: center; box-sizing: border-box; width: 100%;
  }
  .lp-h1 { font-size: clamp(1.4rem, 6.5vw, 2rem) !important; overflow-wrap: break-word; word-break: break-word; }
  .lp-h1 br { display: none; }
  .lp-hero { padding: 0 !important; }
  .lp-lead { font-size: 0.82rem; margin-left: auto; margin-right: auto; max-width: 100%; overflow-wrap: break-word; }
  .lp-badge { font-size: 0.5rem; padding: 0.3rem 0.7rem; }
  .lp-hero-stats { flex-wrap: wrap; gap: 1rem; justify-content: center; }
  .lp-hero-stat { min-width: 0; align-items: center; }
  .lp-hero-stat-label { font-size: 0.5rem; text-align: center; }
  .lp-hero-actions { justify-content: center; gap: 1.2rem; flex-wrap: wrap; }
}
@media (max-width: 480px) {
  .lp-hero-inner { padding: 4rem 0.85rem 2.5rem 0.85rem; }
  .lp-lead { font-size: 0.8rem; line-height: 1.6; }
  .lp-hero-stats { gap: 0.6rem; }
  .lp-hero-stat-val { font-size: 0.9rem; }
  .lp-hero-stat-label { font-size: 0.45rem; }
  .lp-hero-actions { flex-direction: column; gap: 0.8rem; }
  .lp-cta { width: 100%; justify-content: center; padding: 0.75rem 1.5rem; }
}

/* ARCH GRID: 5 cols → 3 → 2 → 1 */
@media (max-width: 900px) {
  .lp-arch-grid { grid-template-columns: repeat(3, 1fr); }
  .lp-arch-item:nth-child(3) { border-right: 1px solid rgba(var(--nc-primary-rgb),0.06); }
}
@media (max-width: 640px) {
  .lp-arch-grid { grid-template-columns: repeat(2, 1fr); }
  .lp-arch-item:nth-child(2n) { border-right: 1px solid rgba(var(--nc-primary-rgb),0.06); }
  .lp-arch-item { padding: 1rem 0.75rem 1.2rem; }
  .lp-arch-name { font-size: 0.72rem; }
  .lp-arch-desc { font-size: 0.62rem; }
}
@media (max-width: 400px) {
  .lp-arch-grid { grid-template-columns: 1fr; }
  .lp-arch-item { border-right: 1px solid rgba(var(--nc-primary-rgb),0.06) !important; }
}

/* TEASER SECTIONS: reduce padding on mobile */
@media (max-width: 640px) {
  .as-teaser, .gl-teaser { padding: 3rem 1rem; }
  .as-stage, .gl-stage { padding: 1.5rem 1.25rem; border-radius: 12px; }
}

/* OPERATOR SECTION: cards stack */
@media (max-width: 640px) {
  .ag-deploy-row { grid-template-columns: 1fr !important; }
}

/* ─────────────────────────────────────────────────────────────
   INDUSTRY BLUEPRINTS — THE ATLAS  (replaced BECOME A BACKER, 2026-08-10)
   Transparent base: rides the page-wide .lp-ambient. No section background,
   no glows of its own — the hairline top border is the only chrome.
   ───────────────────────────────────────────────────────────── */
.lbp {
  position: relative;
  padding: 5rem 0 4.5rem;
  border-top: 1px solid rgba(255, 255, 255, 0.04);
}
.lbp-inner { position: relative; z-index: 2; }
.lbp-eyebrow-mark { color: rgba(var(--nc-primary-rgb), 0.85); margin-right: 0.35rem; }
.lbp-accent { color: rgba(var(--nc-primary-rgb), 0.95); font-weight: 400; }
.lbp-lead { max-width: 720px; }

/* Stat pulse */
.lbp-pulse {
  display: flex; justify-content: center; align-items: stretch;
  gap: 1.6rem; flex-wrap: wrap;
  margin: 0 auto 2.6rem;
}
.lbp-stat { display: flex; flex-direction: column; align-items: center; gap: 4px; min-width: 120px; }
.lbp-stat-num {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 1.7rem; font-weight: 600;
  color: rgba(255, 255, 255, 0.92);
}
.lbp-stat-label {
  font-size: 0.62rem; letter-spacing: 0.14em; text-transform: uppercase;
  color: rgba(255, 255, 255, 0.42); text-align: center; max-width: 160px; line-height: 1.5;
}
.lbp-divider { width: 1px; background: rgba(255, 255, 255, 0.08); }

/* Flagship trio */
.lbp-featured { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; margin-bottom: 1.6rem; }
.lbp-card {
  position: relative; display: flex; flex-direction: column; gap: 0.55rem;
  padding: 1.4rem 1.3rem 1.15rem;
  border: 1px solid rgba(255, 255, 255, 0.07); border-radius: 10px;
  background: rgba(255, 255, 255, 0.015);
  text-decoration: none; overflow: hidden;
  transition: border-color 0.25s ease, transform 0.25s ease, background 0.25s ease;
}
.lbp-card::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(var(--nc-primary-rgb), 0.7), transparent);
  opacity: 0; transition: opacity 0.25s ease;
}
.lbp-card:hover { border-color: rgba(var(--nc-primary-rgb), 0.3); background: rgba(var(--nc-primary-rgb), 0.03); transform: translateY(-2px); }
.lbp-card:hover::before { opacity: 1; }
.lbp-card-rank {
  position: absolute; top: 0.9rem; right: 1.05rem;
  font-family: 'IBM Plex Mono', monospace; font-size: 0.66rem;
  color: rgba(var(--nc-primary-rgb), 0.5);
}
.lbp-card-industry {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.56rem; letter-spacing: 0.18em; text-transform: uppercase;
  color: rgba(255, 255, 255, 0.4); padding-right: 2.2rem;
}
.lbp-card-name { font-size: 1.25rem; font-weight: 600; letter-spacing: 0.06em; color: rgba(255, 255, 255, 0.94); margin: 0; }
.lbp-card-promise { font-size: 0.8rem; line-height: 1.6; color: rgba(255, 255, 255, 0.55); margin: 0; flex: 1; }
.lbp-card-foot { display: flex; align-items: center; gap: 0.45rem; margin-top: 0.35rem; }
.lbp-card-chip {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.54rem; letter-spacing: 0.12em;
  padding: 3px 8px; border-radius: 3px;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.25);
  color: rgba(var(--nc-primary-rgb), 0.75);
}
.lbp-card-chip-amber { border-color: rgba(251, 191, 36, 0.3); color: rgba(251, 191, 36, 0.8); }
.lbp-card-arrow { margin-left: auto; color: rgba(var(--nc-primary-rgb), 0.7); font-size: 0.9rem; transition: transform 0.25s ease; }
.lbp-card:hover .lbp-card-arrow { transform: translateX(3px); }

/* The full atlas index */
.lbp-index {
  display: grid; grid-template-columns: repeat(3, 1fr);
  gap: 2px 1.2rem;
  margin-bottom: 2.4rem;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
  padding-top: 1.1rem;
}
.lbp-row {
  display: flex; align-items: baseline; gap: 0.55rem;
  padding: 0.42rem 0.55rem; border-radius: 5px;
  text-decoration: none; min-width: 0;
  transition: background 0.2s ease;
}
.lbp-row:hover { background: rgba(var(--nc-primary-rgb), 0.05); }
.lbp-row-rank { font-family: 'IBM Plex Mono', monospace; font-size: 0.6rem; color: rgba(var(--nc-primary-rgb), 0.45); flex-shrink: 0; }
.lbp-row-industry { font-size: 0.74rem; color: rgba(255, 255, 255, 0.6); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; min-width: 0; }
.lbp-row:hover .lbp-row-industry { color: rgba(255, 255, 255, 0.85); }
.lbp-row-system { font-family: 'IBM Plex Mono', monospace; font-size: 0.58rem; letter-spacing: 0.1em; color: rgba(var(--nc-primary-rgb), 0.6); flex-shrink: 0; }

/* CTAs */
.lbp-actions { display: flex; justify-content: center; align-items: center; gap: 1rem; flex-wrap: wrap; }
.lbp-cta {
  display: inline-flex; align-items: center; gap: 0.5rem;
  padding: 0.75rem 1.6rem; border-radius: 6px;
  background: rgba(var(--nc-primary-rgb), 0.12);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.4);
  color: rgba(255, 255, 255, 0.95);
  font-size: 0.85rem; font-weight: 600; letter-spacing: 0.02em;
  text-decoration: none;
  transition: background 0.25s ease, box-shadow 0.25s ease;
}
.lbp-cta:hover { background: rgba(var(--nc-primary-rgb), 0.2); box-shadow: 0 6px 24px rgba(var(--nc-primary-rgb), 0.18); }
.lbp-cta-arrow { transition: transform 0.25s ease; }
.lbp-cta:hover .lbp-cta-arrow { transform: translateX(3px); }
.lbp-cta-ghost {
  padding: 0.75rem 1.3rem; border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: rgba(255, 255, 255, 0.6); font-size: 0.85rem; text-decoration: none;
  transition: border-color 0.25s ease, color 0.25s ease;
}
.lbp-cta-ghost:hover { border-color: rgba(251, 191, 36, 0.4); color: rgba(251, 191, 36, 0.85); }

@media (max-width: 1024px) {
  .lbp-featured { grid-template-columns: 1fr; }
  .lbp-index { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 640px) {
  .lbp { padding: 3.5rem 0 3rem; }
  .lbp-index { grid-template-columns: 1fr; }
  .lbp-divider { display: none; }
  .lbp-pulse { gap: 1.1rem; }
}
@media (prefers-reduced-motion: reduce) {
  .lbp-card, .lbp-card::before, .lbp-card-arrow, .lbp-cta-arrow, .lbp-row, .lbp-cta, .lbp-cta-ghost { transition: none; }
  .lbp-card:hover { transform: none; }
  .lbp-card:hover .lbp-card-arrow, .lbp-cta:hover .lbp-cta-arrow { transform: none; }
}

/* GENERAL: prevent horizontal overflow from any section */
@media (max-width: 768px) {
  .lp-container { padding-left: 1rem; padding-right: 1rem; }
  .lp { overflow-x: hidden; }
  .lp-hero { overflow: visible; }
  .lp-hero-inner * { max-width: 100%; box-sizing: border-box; }
}

/* ═══ §2026-06-29 MOBILE — give the AgentWorld globe a dedicated visible band ═══
   On desktop the globe is a full-bleed backdrop behind a 520px text column (so it
   shows on the right). On mobile the text fills the full width + height, drowning
   the globe → it reads as "no globe". Scoped to ≤768px ONLY — desktop is untouched.
   Here the globe becomes a real ~46vh band at the TOP of the hero, with the text
   flowing below it in normal order, so the globe is unmistakably visible. */
@media (max-width: 768px) {
  .lp-hero {
    display: block !important;
    min-height: auto !important;
    padding: 0 0 2.5rem !important;
    overflow: hidden;
    align-items: initial;
  }
  .lp-globe-bg {
    position: relative !important;
    inset: auto !important;
    width: 100%;
    height: 46vh;
    min-height: 300px;
    opacity: 1;
    z-index: 0;
    /* soft-fade the band's bottom edge into the text zone below */
    -webkit-mask-image: linear-gradient(to bottom, #000 80%, transparent 100%);
            mask-image: linear-gradient(to bottom, #000 80%, transparent 100%);
  }
  .lp-globe-bg :deep(.agentworld-container) {
    position: absolute !important; inset: 0;
    width: 100% !important; height: 100% !important;
  }
  .lp-hero-inner {
    position: relative; z-index: 10;
    padding: 1.25rem 1.25rem 0 !important;
    max-width: 100% !important; width: 100%;
    text-align: center; box-sizing: border-box;
  }
}

/* ── EXPLORE INDEX (2026-08-01) ─────────────────────────────────────────────
   Replaces seven full-bleed teaser sections. Deliberately reuses .lp-section /
   .lp-container / .sec-eyebrow / .lp-h2 / .lp-body so it inherits the page's
   existing rhythm and needs no new section chrome. The old teaser CSS is kept
   on purpose: restoring any one teaser then needs only its markup back.        */
.xp-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 14px;
  margin-top: 30px;
}
.xp-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 20px 20px 18px;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.02);
  text-decoration: none;
  transition: border-color .18s ease, background .18s ease, transform .18s ease;
}
.xp-card:hover {
  border-color: rgba(var(--nc-primary-rgb), 0.55);
  background: rgba(var(--nc-primary-rgb), 0.06);
  transform: translateY(-2px);
}
.xp-card:focus-visible {
  outline: 2px solid var(--nc-primary);
  outline-offset: 3px;
}
.xp-card-label {
  font-size: .68rem;
  font-weight: 700;
  letter-spacing: .12em;
  color: var(--nc-primary);
}
.xp-card-desc {
  font-size: .92rem;
  line-height: 1.5;
  color: var(--nc-text-dim, rgba(255,255,255,.72));
  flex: 1;
}
.xp-card-cta {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: .8rem;
  font-weight: 600;
  color: var(--nc-text, #fff);
  opacity: .85;
}
.xp-card:hover .xp-card-cta { opacity: 1; }
@media (max-width: 640px) {
  .xp-grid { grid-template-columns: 1fr; gap: 12px; }
  .xp-card { padding: 16px; }
}
@media (prefers-reduced-motion: reduce) {
  .xp-card, .xp-card:hover { transition: none; transform: none; }
}


/* ═══ §STATUSPAGE — the status line (the bracket lives on /status) ═══ */
.lp-statusline { padding: .35rem 0 0; }
.lp-statusline-inner { display: flex; align-items: center; gap: .6rem; flex-wrap: wrap; padding: .55rem 1rem; border: 1px solid rgba(var(--nc-primary-rgb),.1);
  border-radius: 10px; background: rgba(255,255,255,.015); font-family: 'IBM Plex Mono', monospace; font-size: .66rem; letter-spacing: .06em; }
.lp-status-dot { width: 8px; height: 8px; border-radius: 50%; background: rgba(255,255,255,.2); flex: 0 0 auto; }
.lp-status-dot--up { background: #00c853; box-shadow: 0 0 8px rgba(0,200,83,.6); }
.lp-status-dot--partial { background: #f5a623; box-shadow: 0 0 8px rgba(245,166,35,.6); }
.lp-status-dot--wait { background: rgba(255,255,255,.25); }
.lp-status-text { color: rgba(255,255,255,.85); }
.lp-status-ago { color: rgba(255,255,255,.4); }
.lp-status-link { margin-left: auto; color: rgba(var(--nc-primary-rgb),.85); text-decoration: none; letter-spacing: .1em; text-transform: uppercase; font-size: .6rem; }
.lp-status-link:hover { text-decoration: underline; }
/* ═══ §LPSTRIPS — the three folded strips ═══ */
.lp-strips { padding: 1.4rem 0 .4rem; }
.lp-strips-inner { display: flex; flex-direction: column; gap: .55rem; }
.lp-strips-kicker { margin: 0 0 .1rem; font-family: 'IBM Plex Mono', monospace; font-size: .6rem; letter-spacing: .18em; text-transform: uppercase; color: rgba(var(--nc-primary-rgb),.7); }

</style>
