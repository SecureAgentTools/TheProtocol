<template>
  <!-- §LANDINGDISC-2 — `embedded` renders the RESULTS GRID ONLY (his word: the landing preview must be
       "the current cards of the discovery … with encirclements and everything. clickable modal opens"). One
       view, two densities: the cards, their flares, the provenance badges and the detail modal are literally
       the same code, so the preview cannot drift from the page it previews. -->
  <div class="nc-page nc-discovery-page" :class="{ 'disc-embedded': embedded }">

    <!-- ── Header (§DISCPANEL: eyebrow + H1 + lead, Design_Language.md §4) ──────── -->
    <header class="disc-hero" v-if="!embedded">
      <div class="disc-hero-main">
        <span class="disc-eyebrow">
          <span class="disc-eyebrow-dot"></span>
          {{ tp('discoveryView.hero.eyebrow', '{n} registries · one network', { n: (indexStatus?.registriesTotal || federationPeers.length + 1) }) }}
        </span>
        <h1 class="disc-hero-h1" data-tour="dsc-hero">{{ t('discoveryView.hero.title') }}</h1>
        <p class="disc-hero-lead">{{ t('discoveryView.subtitle') }}</p>
      </div>
      <div class="disc-hero-actions">
        <span v-if="lastRefreshedAgo" class="disc-hero-asof" data-testid="disc-refreshed-ago">
          {{ tp('discoveryView.refreshedAgo', 'updated {t}', { t: lastRefreshedAgo }) }}
        </span>
        <button @click="refreshData" :disabled="loading" class="disc-refresh" data-testid="disc-refresh">
          <NeuralIcon name="refresh" :size="15" :class="{ 'nc-icon-spin': loading }" />
          <span>{{ loading ? t('discoveryView.refreshing', 'Refreshing…') : t('discoveryView.refresh') }}</span>
        </button>
      </div>
    </header>

    <!-- ── Federation Network Strip ──────────────────────────── -->
    <div class="disc-net-strip mb-3" v-if="!embedded && (federationPeers.length > 0 || networkStats)">
      <div class="disc-net-node disc-net-local disc-net-node--clickable" @click="openRegCard(null)" title="View this registry's card" role="button" tabindex="0" @keyup.enter="openRegCard(null)">
        <span class="disc-net-dot disc-net-dot--green"></span>
        <span class="disc-net-label">{{ localRegistryName }}</span>
        <span class="disc-net-count">{{ localAgentCount }}</span>
      </div>
      <div class="disc-net-line">
        <div class="disc-net-pulse"></div>
      </div>
      <div
        v-for="peer in sortedFederationPeers"
        :key="peer.id"
        class="disc-net-node disc-net-peer disc-net-node--clickable"
        :class="peer.status === 'ACTIVE' ? 'disc-net-peer--active' : 'disc-net-peer--inactive'"
        :title="'View ' + peer.name + ' registry card'"
        role="button" tabindex="0"
        @click="openRegCard(peer.name)" @keyup.enter="openRegCard(peer.name)"
      >
        <span class="disc-net-dot" :class="peer.status === 'ACTIVE' ? 'disc-net-dot--cyan' : 'disc-net-dot--gray'"></span>
        <span class="disc-net-label">{{ peer.name }}</span>
        <!-- §DISCFIX — each peer shows ITS OWN agent count from the server
             facets (every chip used to show one shared page-sum, or ↻). -->
        <span class="disc-net-count" v-if="peer.status === 'ACTIVE'">
          {{ peerChipCount(peer.name) ?? '—' }}
        </span>
        <span class="disc-net-badge-active" v-if="peer.status === 'ACTIVE'">{{ t('discoveryView.active') }}</span>
        <span class="disc-net-badge-inactive" v-else>{{ t('discoveryView.inactive') }}</span>
      </div>
      <div class="disc-net-spacer"></div>
      <div class="disc-net-health">
        <span v-if="lastSyncAgo" class="text-xs nc-text-muted mr-3" :title="'Last federation sync: ' + (networkStats?.lastGlobalSync || '')">⟳ {{ lastSyncAgo }}</span>
        <span class="text-xs nc-text-muted">{{ t('discoveryView.networkHealth') }}</span>
        <span class="text-xs font-bold ml-1" :class="networkStats && networkStats.networkHealth >= 90 ? 'text-green-400' : 'text-yellow-400'">
          {{ networkStats ? networkStats.networkHealth.toFixed(0) : '—' }}%
        </span>
        <!-- §DISCPANEL (his ask): the number on each chip had no explanation anywhere on the page. -->
        <button class="disc-info-btn ml-2" type="button" data-testid="disc-strip-info"
                :aria-label="t('discoveryView.strip.whatIsThis', 'What does this bar show?')"
                @click="showStripInfo = !showStripInfo">i</button>
      </div>
    </div>
    <!-- §DISCPANEL fix (his eye): this popover used to sit INSIDE .disc-net-strip, which is `overflow-x: auto`
         — an absolutely-positioned child there is clipped and only lengthens the bar's scroll, so the panel
         never appeared. It lives outside the scrolling element now, anchored to the page column. -->
    <div class="disc-strip-pop-anchor" v-if="!embedded">
      <div v-if="showStripInfo" class="disc-info-pop disc-info-pop--strip" data-testid="disc-strip-info-pop">
        <p class="disc-info-h">{{ t('discoveryView.strip.title', 'This registry and the peers it syncs with') }}</p>
        <p>{{ t('discoveryView.strip.infoCount', 'The number on a chip is how many agents discoverable from here ORIGINATE at that registry — this frame\'s own on the first chip, and each peer\'s mirrored cards after it. It is the server\'s count for the whole federation, not the page you are looking at, so it does not change as you filter.') }}</p>
        <p>{{ t('discoveryView.strip.infoActive', 'ACTIVE means this frame still federates with that peer and keeps pulling its cards. A chip opens that registry\'s signed card.') }}</p>
        <p class="disc-info-dim">{{ t('discoveryView.strip.infoHealth', 'The sync age is this frame\'s last federation cycle; Network Health is the share of peers answering.') }}</p>
      </div>
    </div>

    <!-- §DISCPANEL — the federated INDEX, in the same language: is it live, and which registries does this
         console read from it rather than from its own sync. Renders only where a Directory is configured. -->
    <DirectoryStrip v-if="!embedded" :synced-peers="syncedPeerNames" :local-registry="localRegistryName"
                    :status="indexStatus" :listings="indexListings" :failed-reason="indexFailed" :as-of="indexAsOf" />

    <!-- ── Search + Filter Bar ───────────────────────────────── -->
    <!-- a phone: the DID lookup takes its own line under the search (side by side the search box was squeezed to "Sea…"
         beside it; the camera, 2026-10-13, Pixel 7) -->
    <NeuralCard v-if="!embedded" variant="flat" class="mb-3 py-2 px-3">
      <div class="flex flex-wrap items-center gap-2">
        <div class="flex-1 min-w-0 relative">
          <NeuralIcon name="search" :size="18" class="absolute left-3 top-1/2 -translate-y-1/2 nc-text-muted disc-search-icon" />
          <input
            v-model="searchQuery"
            @input="handleSearch"
            @keyup.enter="performSearch"
            type="text"
            :placeholder="t('discoveryView.searchPlaceholder')"
            class="disc-search-input w-full pl-10 pr-3 py-2.5 text-sm"
          >
        </div>
        <div class="w-full order-last sm:order-none sm:w-40">
          <input
            v-model="didQuery"
            @keyup.enter="lookupDID"
            type="text"
            :placeholder="t('discoveryView.didPlaceholder')"
            class="w-full px-3 py-1.5 text-sm nc-bg-void rounded-sm border border-gray-700 focus:border-cyan-500 transition-colors"
          >
        </div>
        <button @click="toggleView" class="nc-btn nc-btn-ghost p-1.5" title="Toggle view">
          <NeuralIcon v-if="viewMode === 'grid'" name="grid" :size="18" />
          <NeuralIcon v-else name="list" :size="18" />
        </button>
      </div>
    </NeuralCard>

    <!-- ── Stats Bar — §DISCFIX: server aggregates, '—' while loading ──── -->
    <!-- two columns on a phone: four squeezed the labels to "NETWO…" and pushed every value out (the camera, 2026-10-13) -->
    <div class="disc-stats grid grid-cols-2 md:grid-cols-4 gap-2 mb-3" data-tour="dsc-stats" v-if="!embedded">
      <NeuralCard variant="flat" class="py-2 px-3 disc-stat-card" :title="'Distinct agents across this registry and its federation peers (mirrors of one agent counted once)'">
        <div class="flex items-center justify-between disc-stat-row">
          <span class="inline-flex items-center gap-1.5 text-xs uppercase nc-text-muted">
            <NeuralIcon name="globe" :size="13" class="disc-stat-ico" />
            {{ t('discoveryView.stats.networkAgents', 'Network Agents') }}
          </span>
          <span class="text-sm font-bold nc-text-primary">{{ fmtStat(networkTotalAgents) }}</span>
        </div>
      </NeuralCard>
      <NeuralCard variant="flat" class="py-2 px-3 disc-stat-card" :title="'Local agents with a heartbeat in the last 24 hours'">
        <div class="flex items-center justify-between disc-stat-row">
          <span class="inline-flex items-center gap-1.5 text-xs uppercase nc-text-muted">
            <NeuralIcon name="zap" :size="13" class="disc-stat-ico" />
            {{ t('discoveryView.stats.active24h', 'Active (24h)') }}<span class="disc-stat-scope">{{ t('discoveryView.stats.scopeLocal', 'local') }}</span>
          </span>
          <span class="text-sm font-bold nc-text-success inline-flex items-center gap-1.5">
            <span v-if="activeAgents24h !== null" class="disc-live-dot"></span>
            {{ fmtStat(activeAgents24h) }}
          </span>
        </div>
      </NeuralCard>
      <NeuralCard variant="flat" class="py-2 px-3 disc-stat-card" :title="'Local agents with payment_required pricing'">
        <div class="flex items-center justify-between disc-stat-row">
          <span class="inline-flex items-center gap-1.5 text-xs uppercase nc-text-muted">
            <NeuralIcon name="dollar" :size="13" class="disc-stat-ico" />
            {{ t('discoveryView.stats.paidServices') }}<span class="disc-stat-scope">{{ t('discoveryView.stats.scopeLocal', 'local') }}</span>
          </span>
          <span class="text-sm font-bold" style="color: #f59e0b;">{{ fmtStat(paidServiceCount) }}</span>
        </div>
      </NeuralCard>
      <NeuralCard variant="flat" class="py-2 px-3 disc-stat-card" :title="'Units locked in bonds and locks on this frame'">
        <div class="flex items-center justify-between disc-stat-row">
          <span class="inline-flex items-center gap-1.5 text-xs uppercase nc-text-muted">
            <NeuralIcon name="wallet" :size="13" class="disc-stat-ico" />
            {{ t('discoveryView.stats.networkTvl') }}
          </span>
          <span class="text-sm font-bold nc-text-primary">{{ formatAVT(networkTVL) }}</span>
        </div>
      </NeuralCard>
    </div>

    <!-- ── Main Layout ───────────────────────────────────────── -->
    <div class="flex gap-6">

      <!-- Filter Sidebar -->
      <aside class="w-64 shrink-0 hidden lg:block overflow-visible" data-tour="dsc-filters" v-if="!embedded">
        <div class="disc-side-panel p-2 sticky top-6">
          <h3 class="font-semibold mb-2 text-sm nc-text-primary">{{ t('discoveryView.filters.title') }}</h3>

          <!-- Registry Source -->
          <div class="mb-3">
            <h4 class="text-xs font-medium mb-1 nc-text-muted">{{ t('discoveryView.filters.registrySource') }}</h4>
            <div class="space-y-1">
              <label class="flex items-center text-xs gap-1 cursor-pointer">
                <input type="radio" v-model="registryFilter" value="all" @change="applyFilters" class="mr-1 scale-75"> {{ t('discoveryView.filters.allRegistries') }}
              </label>
              <label class="flex items-center text-xs gap-1 cursor-pointer">
                <input type="radio" v-model="registryFilter" value="local" @change="applyFilters" class="mr-1 scale-75">
                <span class="w-2 h-2 rounded-full bg-green-500 inline-block"></span> {{ t('discoveryView.filters.localOnly', 'Local') }} · {{ localRegistryName }}
              </label>
              <label class="flex items-center text-xs gap-1 cursor-pointer">
                <input type="radio" v-model="registryFilter" value="federated" @change="applyFilters" class="mr-1 scale-75">
                <span class="w-2 h-2 rounded-full bg-cyan-500 inline-block"></span> {{ t('discoveryView.filters.federated') }}
              </label>
            </div>
          </div>

          <!-- §pass62.1 (2026-05-21) — Multi-select peer filter.
               Sources peer list from useFederationTopology (full federation roster,
               scales as new peers join). Each row = PeerOrb + name + count.
               Empty selection = show all. URL state ?frames=name1,name2. -->
          <div class="mb-3 disc-frame-filter">
            <div class="flex items-center justify-between mb-1">
              <h4 class="text-xs font-medium nc-text-muted">Filter by Peer</h4>
              <div class="flex gap-1">
                <button
                  v-if="selectedFrames.size > 0"
                  type="button"
                  @click="clearFrames"
                  class="disc-ff-mini-btn"
                  :title="t('discoveryView.filters.frameAny')"
                >clear</button>
                <button
                  v-if="selectedFrames.size < availableFrameOptions.length"
                  type="button"
                  @click="selectAllFrames"
                  class="disc-ff-mini-btn"
                  title="Select all"
                >all</button>
              </div>
            </div>
            <div class="disc-ff-hint" v-if="selectedFrames.size === 0">
              All peers shown — click any to filter
            </div>
            <div class="disc-ff-hint" v-else>
              {{ selectedFrames.size }} of {{ availableFrameOptions.length }} selected
            </div>
            <ul class="disc-ff-list" role="listbox" :aria-label="t('discoveryView.filters.frame')">
              <li
                v-for="opt in availableFrameOptions"
                :key="opt.key"
                class="disc-ff-row"
                :class="{ 'disc-ff-row--active': selectedFrames.has(opt.key), 'disc-ff-row--local': opt.isLocal }"
                role="option"
                :aria-selected="selectedFrames.has(opt.key)"
                tabindex="0"
                @click="toggleFrame(opt.key)"
                @keyup.enter.space="toggleFrame(opt.key)"
              >
                <span class="disc-ff-check" :class="{ 'disc-ff-check--on': selectedFrames.has(opt.key) }">
                  <span v-if="selectedFrames.has(opt.key)">✓</span>
                </span>
                <span class="disc-ff-orb">
                  <PeerOrb v-if="opt.peer" :peer="(opt.peer as any)" :radius="8" :is-local="opt.isLocal" :tier="opt.peer?.peer_type || 'discovered'" />
                  <span v-else class="disc-ff-orb-fallback" />
                </span>
                <span class="disc-ff-label" :title="opt.label">{{ opt.label }}</span>
                <span class="disc-ff-count" :class="{ 'disc-ff-count--zero': opt.count === 0 }">{{ opt.count }}</span>
                <!-- §NUMALIGN — only when the index disagrees with the list, and only then. The gap is
                     always the bond gate: an agent must hold a reputation bond to be listed here, and
                     system agents (the FX router, the canaries, a treasury) never do. -->
                <span v-if="peerIndexExtra(opt) > 0" class="disc-ff-idx"
                      :title="tp('discoveryView.filters.idxTitle',
                               '{n} more published by this registry than are listed here — they hold no reputation bond, which is what listing requires. The federated index bar above counts all of them.',
                               { n: peerIndexExtra(opt) })">+{{ peerIndexExtra(opt) }}</span>
              </li>
            </ul>
          </div>

          <!-- Tag (§DISCFIX — server-faceted; replaces the derived pseudo-category) -->
          <div class="mb-3">
            <h4 class="text-xs font-medium mb-1 nc-text-muted">{{ t('discoveryView.filters.tag', 'Tag') }}</h4>
            <select
              v-model="filters.tag"
              :aria-label="t('discoveryView.filters.tag', 'Tag')"
              @change="applyFilters"
              class="w-full px-2 py-1 text-xs rounded-sm border nc-bg-void nc-text-primary"
              style="border-color: rgba(var(--nc-primary-rgb),0.25);"
            >
              <option value="">{{ t('discoveryView.filters.allTags', 'All tags') }}</option>
              <option v-for="tg in availableFilters.tags" :key="tg.name" :value="tg.name">
                {{ tg.name }} ({{ tg.count }})
              </option>
            </select>
          </div>

          <!-- Pricing -->
          <div class="mb-3">
            <h4 class="text-xs font-medium mb-1 nc-text-muted">{{ t('discoveryView.filters.pricing') }}</h4>
            <div class="space-y-1">
              <label v-for="model in availableFilters.pricing_models.slice(0, 3)" :key="model.model" class="flex items-center text-xs">
                <input type="radio" v-model="filters.pricing_model" :value="model.model" @change="applyFilters" class="mr-1 scale-75">
                {{ translatePricingLabel(model) }}
              </label>
            </div>
          </div>

          <!-- Other -->
          <div class="mb-3 space-y-1">
            <label class="flex items-center text-xs">
              <input type="checkbox" v-model="filters.is_certified" @change="applyFilters" class="mr-1 scale-75">
              {{ t('discoveryView.filters.certifiedOnly') }}
            </label>
            <label class="flex items-center text-xs" title="Local agents with a heartbeat in the last 24 hours">
              <input type="checkbox" v-model="filters.is_online" @change="applyFilters" class="mr-1 scale-75">
              {{ t('discoveryView.filters.active24h', 'Active in last 24h') }}
            </label>
          </div>

          <!-- §MARKCOLLAR-2 — the tier legend lives HERE, on the surface where
               people meet the marks, not on the globe. It renders the real
               EarnedMarkCollar per tier, so it cannot drift from the cards. -->
          <div class="mb-3 flex items-center gap-1.5" data-testid="disc-earned-legend-row">
            <h4 class="text-xs font-medium nc-text-muted">{{ t('discoveryView.filters.earnedMarks', 'Earned marks') }}</h4>
            <EarnedMarkLegend />
            <span class="text-[10px] nc-text-muted opacity-70">{{ t('discoveryView.filters.whatsThis', 'what do these mean?') }}</span>
          </div>
          <!-- §MARKSURFACES / §DISCMIX — SAY WHICH ZERO THIS IS. A legend that explains
               seven tiers above a page where nothing wears one reads as a broken feature,
               and that is precisely what happened: the flagship moved to a frame whose
               guild ledger is empty, every avatar correctly rendered nothing, and the
               conclusion was that the ranking display had been deleted. A filter that
               removes EVERYTHING is indistinguishable from an outage unless it counts. -->
          <p v-if="earnedMarkCensus" class="disc-mark-census" data-testid="disc-earned-census">
            {{ earnedMarkCensus }}
          </p>

          <!-- §DISCPANEL — TRUST: the three controls that decide who is even in the population, grouped and
               named. The bond one is not a preference: under enforce this registry REMOVES unbonded providers
               from the page, the facets and the counts, and nothing on screen said so until now. -->
          <div class="mb-3 disc-filter-group" data-testid="disc-trust-filters">
            <h4 class="text-xs font-medium mb-1 nc-text-muted">{{ t('discoveryView.filters.trust', 'Trust') }}</h4>
            <label class="disc-bond-filter" data-testid="disc-bond-filter" :title="t('discoveryView.bond.filterTitle', 'Only agents whose home registry holds a reputation bond in escrow')">
              <input type="checkbox" v-model="filters.bonded_only" @change="performSearch" />
              <Icon name="mdi:shield-account" />
              <span>{{ t('discoveryView.bond.filterBonded', 'Bonded only') }}</span>
            </label>
            <label class="flex items-center text-xs gap-1 cursor-pointer mt-1" data-testid="disc-unbonded-filter"
                   :title="t('discoveryView.filters.includeUnbondedTitle', 'This registry enforces the reputation bond: an agent without one is removed from discovery entirely. Tick this to see them.')">
              <input type="checkbox" v-model="filters.include_unbonded" @change="performSearch" class="mr-1 scale-75" />
              {{ t('discoveryView.filters.includeUnbonded', 'Include agents without a bond') }}
            </label>
            <!-- §FESUITE: the registry echoes what it applied (applied_filters). Where the bond is enforced the box binds
                 for the frame's admin only; for anyone else the list does not change, so the page says so instead of
                 leaving the box's promise standing -->
            <p v-if="unbondedRefused" class="disc-unbonded-refused" data-testid="disc-unbonded-refused" role="status">
              {{ t('discoveryView.filters.includeUnbondedRefused', 'Not applied: this registry lists only agents with a bond, and only its admin can include the others.') }}
            </p>
            <label class="flex items-center text-xs gap-1 cursor-pointer mt-1" data-testid="disc-answerable-filter"
                   :title="t('discoveryView.filters.answerableTitle', 'Only agents that have described themselves and whose last health probe did not fail')">
              <input type="checkbox" v-model="filters.answerable_only" @change="performSearch" class="mr-1 scale-75" />
              {{ t('discoveryView.filters.answerable', 'Answers a probe') }}
            </label>
          </div>

          <!-- Sort -->
          <div class="mb-2">
            <h4 class="text-xs font-medium mb-1 nc-text-muted">{{ t('discoveryView.filters.sortBy') }}</h4>
            <select
              v-model="filters.sort_by"
              :aria-label="t('discoveryView.filters.sortBy', 'Sort by')"
              @change="applyFilters"
              class="w-full px-2 py-1 text-xs rounded-sm border nc-bg-void nc-text-primary"
              style="border-color: rgba(var(--nc-primary-rgb),0.25);"
            >
              <option value="proven">{{ t('discoveryView.sort.proven', 'Proven work') }}</option>
              <option value="relevance">{{ t('discoveryView.sort.relevance') }}</option>
              <option value="reputation">{{ t('discoveryView.sort.reputation') }}</option>
              <option value="price_low">{{ t('discoveryView.sort.priceLow') }}</option>
              <option value="price_high">{{ t('discoveryView.sort.priceHigh') }}</option>
              <option value="created">{{ t('discoveryView.sort.newest') }}</option>
            </select>
          </div>

          <button @click="clearAllFilters" class="w-full px-2 py-1 nc-bg-void rounded-sm text-xs nc-text-muted hover:nc-text-primary transition-colors border border-gray-700">
            {{ t('discoveryView.filters.clearAll') }}
          </button>
        </div>
      </aside>

      <!-- Main Content -->
      <div class="flex-1">

        <!-- Distinguished Agents — bearing an encirclement flare (replaces "Featured") -->
        <section v-if="!embedded && showEncircled && !searchQuery && encircledAgents.length > 0" class="mb-8">
          <h2 class="text-xl font-semibold mb-1 nc-text-primary disc-section-h" data-tour="dsc-featured">
            <span class="disc-section-accent disc-section-accent--gold"></span>
            Distinguished Agents
            <span class="disc-section-count">{{ encircledAgents.length }}</span>
          </h2>
          <p class="text-xs nc-text-muted mb-4" data-testid="disc-encircled-subtitle">{{ encircledAreMarked
            ? 'Agents with verified guild work, ranked by what their registry settled'
            : 'Agents bearing an encirclement flare that have described themselves. None has verified guild work here yet.' }}</p>
          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            <div
              v-for="agent in encircledAgents"
              :key="agent.id || agent.did"
              class="disc-featured-card fc-dense cursor-pointer"
              :class="{ 'disc-agent-card--fx-locked': fxStateFor(agent).locked }"
              :title="fxStateFor(agent).locked ? fxHint(agent) : undefined"
              @click="viewAgentByDID(agent.agent_did || agent.did || agent.id)"
            >
              <div class="flex flex-wrap items-center justify-between gap-1 mb-2">
                <!-- UserAvatar renders the agent's encirclement (the whole point of this grid) -->
                <UserAvatar
                  :user="agent"
                  :avatar-url="agent.card_data?.iconUrl || agent.card_data?.icon_url || null"
                  :display-name="agent.name || agent.did"
                  size="md"
                />
                <div class="flex flex-wrap items-center justify-end gap-1 ml-auto">
                  <span v-if="fxStateFor(agent).via" class="disc-fx-badge" :title="'Cross-currency — payable via FX, settles in ' + fxStateFor(agent).ccy">⇄ via FX · {{ fxStateFor(agent).ccy }}</span>
                  <span v-else-if="fxStateFor(agent).locked" class="disc-fx-locked-badge" :title="fxHint(agent)">⇄ {{ fxStateFor(agent).ccy }} · FX off</span>
                  <span class="disc-prov-badge" :class="'disc-prov-badge--' + provenanceOf(agent).kind" :title="provenanceOf(agent).title" data-testid="disc-prov-badge">{{ provenanceOf(agent).kind === 'index' ? '◇' : provenanceOf(agent).kind === 'sync' ? '⬡' : '⌂' }} {{ provenanceOf(agent).label }}</span><span v-if="registryTrustOf(agent)" class="disc-regtrust" :class="'disc-regtrust--' + registryTrustOf(agent)!.state" :title="registryTrustOf(agent)!.title" data-testid="disc-regtrust"><span class="disc-regtrust-dot"></span>{{ registryTrustOf(agent)!.short }}</span>
                </div>
              </div>
              <h3 class="font-semibold mb-1 nc-text-primary truncate">
                <!-- §FESUITE: this card answered only a mouse; its name is the keyboard's way in -->
                <button
                  type="button"
                  class="disc-card-open"
                  :aria-label="tp('discoveryView.openAgent', 'View {name}', { name: agent.name || 'agent' })"
                  @click.stop="viewAgentByDID(agent.agent_did || agent.did || agent.id)"
                >{{ agent.name }}</button>
              </h3>
              <div class="mb-2">
                <span v-if="agent.pricing" class="disc-price-hero disc-price-hero--paid">
                  {{ agent.pricing.base_rate }} <small>{{ currencyForItem(agent) }}/req</small>
                </span>
                <span v-else class="disc-price-hero disc-price-hero--free">Free</span>
              </div>
              <p class="text-xs nc-text-muted mb-3 line-clamp-2">{{ agent.description }}</p>
              <div class="flex items-center justify-between text-xs nc-text-muted">
                <span class="flex items-center gap-1" :class="trustColor(agent)">
                  <span class="w-1.5 h-1.5 rounded-full" :class="trustDotCls(agent)"></span>
                  {{ trustLabel(agent) }}
                </span>
                <span v-if="agent.is_live" class="disc-badge-active inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full" title="Heartbeat seen in the last 24 hours">
                  <span class="w-1.5 h-1.5 rounded-full bg-green-400 disc-dot-pulse"></span> live
                </span>
              </div>
            </div>
          </div>
        </section>

        <!-- Cross-currency Agents — foreign-frame agents (B9, surfaced past the fetch cap) -->
        <!-- §DISCMIX (2026-09-06, his word) — the "Cross-currency Agents" section is RETIRED. A foreign-frame
             agent is not a different kind of thing, it is an agent whose home settles in another currency:
             it sorts with everything else, keeps its purple skin as the marker, and is reachable through the
             ordinary FX filter. One list; the filters do the splitting. -->

        <!-- §FIRMHIRE (H3.2) — FIRMS, proof-ranked; engage opens the intake agent
             through the SAME agent modal every other row uses (one engage brain). -->
        <FirmsLane @engage="viewAgentByDID" />

        <!-- §DISCMIX — the index's rows are IN the list above now (his "sorting mix all sources"), so the
             separate lane is retired. What is left of it lives on the index bar at the top: which registries it
             reads, how deep, and the venues in the federation. -->

        <!-- §DISCMIX — one list, and it says what it is made of. -->
        <!-- ⚠ `indexWithheld` IS IN THIS CONDITION ON PURPOSE (2026-09-08). §DISCMIX's own rule is
             "a gate that removes EVERYTHING is indistinguishable from an outage — name what it
             withheld and carry the switch", and the switch lived inside a block that only rendered
             when something had NOT been removed. On a frame that mirrors its whole federation the
             index contributes 0 rows of its own, so `foreign` and `index` are both 0, the line
             vanished, and the page showed 38 under a header saying 56 with nothing on screen to
             explain the other 18. The rule was written and then gated out of existence. -->
        <div v-if="!embedded && !searchQuery && (mixCounts.foreign || mixCounts.index || indexWithheld)" class="disc-mix-line" data-testid="disc-mix-line">
          {{ mixCounts.index || !indexWithheld
             ? tp('discoveryView.mix.line', '{p} from this registry · {f} cross-currency · {i} seen only through the index',
                  { p: mixCounts.page, f: mixCounts.foreign, i: mixCounts.index })
             : tp('discoveryView.mix.lineNoIndex', '{p} from this registry · {f} cross-currency',
                  { p: mixCounts.page, f: mixCounts.foreign }) }}
          <button v-if="indexWithheld" class="disc-mix-more" data-testid="disc-mix-withheld" @click="filters.include_unbonded = true; performSearch()">
            {{ tp('discoveryView.mix.withheld', '+{n} more in the index without a bond — show them', { n: indexWithheld }) }}
          </button>
          <span v-if="indexFailed" class="disc-mix-warn">{{ t('discoveryView.mix.indexDown', 'the index is unreachable — this list is this registry only') }}</span>
        </div>

        <!-- Loading — skeleton shimmer grid (perceived perf on heavy frames) -->
        <div v-if="loading" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" role="status" aria-busy="true" aria-label="Loading agents">
          <div v-for="n in 9" :key="'skel-'+n" class="disc-skel-card">
            <div class="disc-skel-row">
              <div class="disc-skel-avatar disc-shimmer"></div>
              <div class="flex-1">
                <div class="disc-skel-line disc-shimmer" style="width:62%"></div>
                <div class="disc-skel-line disc-shimmer" style="width:38%;height:9px;margin-top:7px"></div>
              </div>
            </div>
            <div class="disc-skel-line disc-shimmer" style="width:100%;margin-top:12px"></div>
            <div class="disc-skel-line disc-shimmer" style="width:84%;margin-top:7px"></div>
            <div class="disc-skel-chips">
              <span class="disc-skel-chip disc-shimmer"></span>
              <span class="disc-skel-chip disc-shimmer"></span>
              <span class="disc-skel-chip disc-shimmer"></span>
            </div>
          </div>
        </div>

        <!-- Results Header -->
        <div v-if="!embedded && !loading && searchResults.length > 0" class="flex items-center justify-between mb-4">
          <h2 class="text-xl font-semibold nc-text-primary">
            {{ searchQuery ? t('discoveryView.searchResults') : t('discoveryView.allAgents') }}
            <!-- §DISCMIX — count what is ON SCREEN. The list is one merge of three sources now, so the
                 page count alone read 30/54 above 35 cards (and above 100 once the index folds in). -->
            <span class="text-sm nc-text-muted ml-2">({{ filteredResults.length.toLocaleString(appLocale()) }} / {{ totalShown.toLocaleString(appLocale()) }})</span>
          </h2>
          <div v-if="suggestions && suggestions.length > 0 && searchQuery" class="hidden md:flex items-center gap-2 text-sm">
            <span class="nc-text-muted">Try also:</span>
            <button
              v-for="s in suggestions.slice(0, 3)" :key="s"
              @click="searchQuery = s; performSearch()"
              class="px-2 py-1 text-xs nc-bg-void nc-text-primary rounded-sm border border-cyan-500/30 hover:border-cyan-500/70 transition-colors"
            >{{ s }}</button>
          </div>
        </div>

        <!-- §FESUITE: a read that failed is not an empty list: it says so, and offers the read again -->
        <div v-if="!loading && readFailed" class="text-center py-16" role="alert" data-testid="disc-read-failed">
          <h3 class="text-xl font-semibold mb-2 nc-text-primary">{{ t('discoveryView.readFailed', 'The agent list could not be read just now.') }}</h3>
          <p class="nc-text-muted mb-6">{{ t('discoveryView.readFailedHint', 'Nothing was filtered out. Try again in a moment.') }}</p>
          <button @click="performSearch()" class="nc-btn nc-btn-ghost" data-testid="disc-read-retry">{{ t('discoveryView.retry', 'Try again') }}</button>
        </div>

        <!-- Empty State -->
        <div v-else-if="!loading && searchResults.length === 0" class="text-center py-16">
          <div class="w-32 h-32 mx-auto mb-6 relative">
            <div class="absolute inset-0 bg-cyan-500/10 rounded-full animate-pulse" />
            <div class="relative flex items-center justify-center h-full">
              <NeuralIcon name="search" :size="64" color="primary" />
            </div>
          </div>
          <h3 class="text-xl font-semibold mb-2 nc-text-primary">
            <template v-if="searchQuery">No agents match "{{ searchQuery }}"</template>
            <template v-else>No agents found</template>
          </h3>
          <p class="nc-text-muted mb-6">Try a broader term, clear the registry/frame filters, or browse the showcases above.</p>
          <button @click="clearAllFilters" class="nc-btn nc-btn-ghost">Clear Filters</button>
        </div>

        <!-- Grid View -->
        <div v-else-if="viewMode === 'grid'" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <!-- §DISCMIX — ONE card for every source. `--fx` keeps his purple as the marker for a cross-currency
               agent (a skin, at the same size as every other card, not a section of its own); `--index` marks a
               row this frame does not mirror, which opens at its home instead of here. -->
          <div
            v-for="(agent, idx) in filteredResults"
            :key="agent.id || agent.did"
            data-tour="dsc-card"
            class="disc-agent-card fc-dense disc-card-enter group cursor-pointer"
            :class="{
              'disc-agent-card--paid': agent.is_paid,
              'disc-agent-card--fx-locked': fxStateFor(agent).locked,
              'disc-agent-card--fx': fxStateFor(agent).via || fxStateFor(agent).locked,
              'disc-agent-card--index': agent.__index,
            }"
            :style="{ '--enter-i': Math.min(idx, 24) }"
            :title="agent.__index ? tp('discoveryView.index.openHint', 'Indexed at {r} — this frame does not mirror it; opens at its home', { r: agent.origin_registry_name })
                    : (fxStateFor(agent).locked ? fxHint(agent) : undefined)"
            @click="agent.__index ? openAtHome(agent) : viewAgentByDID(agent.agent_did || agent.did || agent.id)"
          >
            <!-- §FESUITE: the card was role="button" around its own buttons (axe nested-interactive, 162 nodes on one
                 page; a screen reader heard only "View X, button"). The card stays clickable for a mouse; for a keyboard
                 and a screen reader the agent's NAME below is the button that opens it. -->
            <!-- Source badge + liveness (§DISCFIX: real heartbeat, not is_active) -->
            <!-- the badges wrap, the right cluster stays right: in a ~270 px card the registry's verdict ran past the card
                 (the camera, 2026-10-13) -->
            <div class="flex flex-wrap items-center justify-between gap-1 mb-2">
              <div class="flex items-center gap-2">
                <span
                  v-if="liveState(agent)"
                  class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium"
                  :class="liveState(agent)!.cls"
                  :title="liveState(agent)!.title"
                >
                  <span class="w-1.5 h-1.5 rounded-full" :class="[liveState(agent)!.dot, agent.is_live ? 'disc-dot-pulse' : '']"></span>
                  {{ liveState(agent)!.label }}
                </span>
                <span v-if="agent.is_certified" class="text-xs text-cyan-400 font-medium">✓ Certified</span>
              </div>
              <div class="flex flex-wrap items-center justify-end gap-1 ml-auto">
                <!-- B8: FX-aware cross-currency indicator -->
                <span v-if="fxStateFor(agent).via" class="disc-fx-badge" :title="'Cross-currency — payable via FX, settles in ' + fxStateFor(agent).ccy">⇄ via FX · {{ fxStateFor(agent).ccy }}</span>
                <span v-else-if="fxStateFor(agent).locked" class="disc-fx-locked-badge" :title="fxHint(agent)">⇄ {{ fxStateFor(agent).ccy }} · FX off</span>
                <span class="disc-prov-badge" :class="'disc-prov-badge--' + provenanceOf(agent).kind" :title="provenanceOf(agent).title" data-testid="disc-prov-badge">
                  {{ provenanceOf(agent).kind === 'index' ? '◇' : provenanceOf(agent).kind === 'sync' ? '⬡' : '⌂' }} {{ provenanceOf(agent).label }}
                </span>
                <span v-if="registryTrustOf(agent)" class="disc-regtrust" :class="'disc-regtrust--' + registryTrustOf(agent)!.state" :title="registryTrustOf(agent)!.title" data-testid="disc-regtrust"><span class="disc-regtrust-dot"></span>{{ registryTrustOf(agent)!.short }}</span>
              </div>
            </div>

            <!-- §pass8 (2026-05-15): avatar (with flare composition) + name + price row.
                 UserAvatar handles local flare + federated card_data.flare uniformly. -->
            <div class="flex items-start gap-3 mb-2">
              <!-- §AGENTDISC #190 — ledger-earned ring (distinct class from cosmetic flares) -->
              <EarnedMarkRing :tr="agent.track_record">
                <UserAvatar
                  :user="agent"
                  :avatar-url="agent.card_data?.iconUrl || agent.card_data?.icon_url || null"
                  :display-name="agent.name || agent.did"
                  size="md"
                  class="disc-card-avatar"
                />
              </EarnedMarkRing>
              <div class="flex-1 min-w-0">
                <h3 class="font-semibold text-base mb-1 nc-text-primary truncate">
                  <button
                    type="button"
                    class="disc-card-open"
                    data-testid="disc-card-open"
                    :aria-label="tp('discoveryView.openAgent', 'View {name}', { name: agent.name || 'agent' })"
                    @click.stop="agent.__index ? openAtHome(agent) : viewAgentByDID(agent.agent_did || agent.did || agent.id)"
                  ><span v-html="sanitizeHighlight(agent.highlights?.name || agent.name || 'Unnamed Agent')"></span></button>
                </h3>
                <div class="flex items-center gap-2 flex-wrap">
                  <span v-if="agent.pricing" class="disc-price-hero disc-price-hero--paid">
                    {{ agent.pricing.base_rate }} <small>{{ currencyForItem(agent) }}/req</small>
                  </span>
                  <span v-else class="disc-price-hero disc-price-hero--free">Free</span>
                  <!-- §REPBOND (2026-09-05) — the bond chip: locked or matured, with the amount.
                       One component for both densities (BondChip.vue). -->
                  <BondChip :bond="agent.reputation?.bond" :is-bonded="!!agent.is_bonded"
                            :volume="agent.reputation?.volume" :fallback-currency="currencyForItem(agent)" />
                  <!-- §V0064 P2 — AGORA equity chip: this agent's org is publicly
                       listed → $TICKER; click → Stocks Discovery for the book. -->
                  <button
                    v-if="equityFor(agent)"
                    class="disc-equity-chip"
                    :title="`${equityFor(agent)!.symbol} listed on AGORA, view on AGORA Listings`"
                    @click.stop="goToStock(equityFor(agent)!)"
                  >
                    <Icon name="mdi:chart-candlestick" />
                    <span class="disc-equity-sym">${{ equityFor(agent)!.symbol }}</span>
                    <span v-if="equityFor(agent)!.last" class="disc-equity-px">{{ equityFor(agent)!.last }}</span>
                  </button>
                </div>
              </div>
            </div>

            <!-- HRI -->
            <div class="text-xs nc-text-muted font-mono mb-2 truncate" :title="agent.did || agent.humanReadableId">
              {{ agent.humanReadableId || agent.did || agent.id }}
            </div>

            <!-- Description -->
            <p class="text-xs nc-text-muted mb-2 line-clamp-3" v-html="sanitizeHighlight(agent.highlights?.description || agent.description || 'No description')"></p>

            <!-- §pass18 — Mini skill / tag chips (max 4) so users scan capabilities at a glance -->
            <div v-if="agent.tags && agent.tags.length > 0" class="disc-card-chips" data-tour="dsc-chips">
              <span v-for="tag in agent.tags.slice(0, 4)" :key="`chip-${tag}`" class="disc-card-chip">{{ tag }}</span>
              <span v-if="agent.tags.length > 4" class="disc-card-chip disc-card-chip--more">+{{ agent.tags.length - 4 }}</span>
            </div>

            <!-- §BONDFILL (2026-09-11) — how far the bond is from maturity, as a thing that
                 fills up. Sits between the collateral (the chip above) and the record (the band
                 below) because that is what it joins: what this provider has at stake, and how
                 long it has had it there. Renders nothing for an agent with no bond. -->
            <BondMaturityBar :bond="agent.reputation?.bond" :origin="agent.originRegistry || agent.origin_registry_name" />

            <!-- §AGENTDISC #188 — Proven-work band (grid card): registry-attested guild
                 history; opens the receipts drawer with in-browser verification. -->
            <div
              v-if="agent.track_record && agent.track_record.jobs > 0"
              class="disc-tr-band mb-2"
              :data-testid="`disc-tr-band-${agent.agent_did || agent.did}`"
              :title="t('discoveryView.tr.bandHint', 'Registry-attested guild work history. Click for verifiable receipts.')"
              @click.stop="openTrackRecord(agent)"
            >
              <span class="disc-tr-chip disc-tr-chip--jobs">
                &#10003; {{ agent.track_record.jobs }} {{ trJobsLabel(agent.track_record.jobs) }}
              </span>
              <span v-if="agent.track_record.stars" class="disc-tr-chip disc-tr-chip--stars">
                &#9733; {{ agent.track_record.stars }}
              </span>
              <span v-if="agent.track_record.cross_registry > 0" class="disc-tr-chip disc-tr-chip--xreg">
                &#11041; {{ agent.track_record.cross_registry }}
              </span>
              <span v-if="agent.track_record.disputes > 0" class="disc-tr-chip disc-tr-chip--disputes">
                {{ agent.track_record.disputes }} {{ t('discoveryView.tr.disputed', 'disputed') }}
              </span>
              <span class="disc-tr-more">{{ t('discoveryView.tr.receipts', 'receipts') }} &#9656;</span>
            </div>

            <!-- Bottom row: trust + date -->
            <div class="flex items-end justify-between">
              <div class="flex items-center gap-3 text-xs">
                <span class="flex items-center gap-1" :class="trustColor(agent)">
                  <span class="w-1.5 h-1.5 rounded-full" :class="trustDotCls(agent)"></span>
                  {{ trustLabel(agent) }}
                </span>
                <!-- §AGENTDISC #191 — why-ranked-here (proven sort only) -->
                <button
                  v-if="filters.sort_by === 'proven'"
                  class="disc-why-chip"
                  :data-testid="`disc-why-${agent.agent_did || agent.did}`"
                  :title="t('discoveryView.rank.whyHint', 'How this ranking position is computed')"
                  @click.stop="toggleRankWhy(agent)"
                >{{ t('discoveryView.rank.why', 'why?') }}</button>
              </div>
              <div class="flex items-center gap-2 text-xs nc-text-muted">
                <span>{{ formatRelativeTime(agent.created_at) }}</span>
                <button
                  @click.stop="viewAgentByDID(agent.agent_did || agent.did || agent.id)"
                  class="p-1 rounded-sm opacity-0 group-hover:opacity-100 focus-visible:opacity-100 touch:opacity-100 transition-opacity hover:bg-cyan-500/10"
                  title="View Details"
                >
                  <svg class="w-4 h-4 text-cyan-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                      d="M15 12a3 3 0 11-6 0 3 3 0 016 0zM2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/>
                  </svg>
                </button>
              </div>
            </div>

            <!-- §AGENTDISC #191 — why-ranked-here breakdown: contributions recomputed
                 from the card's own visible numbers with server-declared weights -->
            <div v-if="rankOpenId === agent.id" class="disc-why-pop" data-testid="disc-why-pop" @click.stop>
              <div v-for="row in rankBreakdown(agent).rows" :key="row.label" class="disc-why-row">
                <span class="disc-why-label">{{ row.label }}</span>
                <span class="disc-why-value">{{ row.value }}</span>
                <span class="disc-why-pts" :class="row.pts >= 0 ? 'trp-okc' : 'trp-latec'">
                  {{ row.pts >= 0 ? '+' : '' }}{{ row.pts }}
                </span>
              </div>
              <div v-if="!agent.track_record" class="disc-why-note">
                {{ t('discoveryView.rank.noHistory', 'No verified guild history yet; position comes from the reputation tiebreak.') }}
              </div>
              <div class="disc-why-total">
                {{ t('discoveryView.rank.score', 'proof score') }}: {{ rankBreakdown(agent).total }}
                <span class="disc-why-formula" :title="rankingMeta?.formula || ''">{{ t('discoveryView.rank.formulaHint', 'open formula') }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- List View -->
        <div v-else class="space-y-3">
          <div
            v-for="agent in filteredResults"
            :key="agent.id || agent.did"
            class="disc-list-card group cursor-pointer"
            :class="{ 'disc-agent-card--fx-locked': fxStateFor(agent).locked }"
            :title="fxStateFor(agent).locked ? fxHint(agent) : undefined"
            @click="viewAgentByDID(agent.agent_did || agent.did || agent.id)"
          >
            <div class="flex items-start gap-4">
              <!-- Price column -->
              <div class="shrink-0 w-16 text-center pt-1">
                <div v-if="agent.pricing" class="text-base font-bold" style="color: #f59e0b;">
                  {{ agent.pricing.base_rate }}
                </div>
                <div v-else class="text-base font-bold text-green-500/70">—</div>
                <div class="text-xs nc-text-muted">{{ agent.pricing ? currencyForItem(agent) : 'Free' }}</div>
              </div>

              <!-- Main content -->
              <div class="flex-1 min-w-0">
                <div class="flex items-start justify-between mb-1">
                  <div class="flex items-center gap-2 flex-wrap">
                    <h3 class="font-semibold nc-text-primary" v-html="sanitizeHighlight(agent.highlights?.name || agent.name)"></h3>
                    <span v-if="liveState(agent)" class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm text-xs"
                          :class="liveState(agent)!.cls" :title="liveState(agent)!.title">
                      <span class="w-1.5 h-1.5 rounded-full" :class="[liveState(agent)!.dot, agent.is_live ? 'disc-dot-pulse' : '']"></span>
                      {{ liveState(agent)!.label }}
                    </span>
                    <span v-if="agent.is_certified" class="text-xs text-cyan-400">✓ Certified</span>
                    <!-- §BATCH0911 item 3 — the list density carries the bond chip too (it never did). -->
                    <BondChip :bond="agent.reputation?.bond" :is-bonded="!!agent.is_bonded"
                              :volume="agent.reputation?.volume" :fallback-currency="currencyForItem(agent)" />
                    <span class="disc-prov-badge" :class="'disc-prov-badge--' + provenanceOf(agent).kind" :title="provenanceOf(agent).title">{{ provenanceOf(agent).kind === 'index' ? '◇' : provenanceOf(agent).kind === 'sync' ? '⬡' : '⌂' }} {{ provenanceOf(agent).label }}</span><span v-if="registryTrustOf(agent)" class="disc-regtrust" :class="'disc-regtrust--' + registryTrustOf(agent)!.state" :title="registryTrustOf(agent)!.title" data-testid="disc-regtrust"><span class="disc-regtrust-dot"></span>{{ registryTrustOf(agent)!.short }}</span>
                    <span v-if="fxStateFor(agent).via" class="disc-fx-badge" :title="'Cross-currency — payable via FX, settles in ' + fxStateFor(agent).ccy">⇄ via FX · {{ fxStateFor(agent).ccy }}</span>
                    <span v-else-if="fxStateFor(agent).locked" class="disc-fx-locked-badge" :title="fxHint(agent)">⇄ {{ fxStateFor(agent).ccy }} · FX off</span>
                  </div>
                  <span class="flex items-center gap-1 text-xs shrink-0 ml-2" :class="trustColor(agent)">
                    {{ trustLabel(agent) }}
                  </span>
                </div>

                <div class="text-xs nc-text-muted font-mono mb-1 truncate">{{ agent.humanReadableId || agent.did }}</div>
                <p class="text-sm nc-text-muted" v-html="sanitizeHighlight(agent.highlights?.description || agent.description || 'No description')"></p>

                <!-- Rep bar (§DISCFIX: EigenTrust scores exceed 100 — clamp the bar) -->
                <div class="disc-rep-bar mt-2 w-48">
                  <div class="disc-rep-fill" :style="{ width: `${Math.min(agent.reputation_score || 0, 100)}%` }" :class="reputationBarClass(agent.reputation_score || 0)"></div>
                </div>

                <!-- §BONDFILL — the same maturity bar in the list density; the bond CHIP sits in
                     the badge row above since §BATCH0911 (item 3). -->
                <div class="mt-2 w-48">
                  <BondMaturityBar :bond="agent.reputation?.bond" :origin="agent.originRegistry || agent.origin_registry_name" />
                </div>

                <!-- §AGENTDISC #188 — Proven-work band: registry-attested guild history.
                     Every figure opens the receipts drawer where each engagement is
                     verifiable in-browser (digest binding + Ed25519 credential). -->
                <div
                  v-if="agent.track_record && agent.track_record.jobs > 0"
                  class="disc-tr-band mt-2"
                  :data-testid="`disc-tr-band-${agent.agent_did || agent.did}`"
                  :title="t('discoveryView.tr.bandHint', 'Registry-attested guild work history. Click for verifiable receipts.')"
                  @click.stop="openTrackRecord(agent)"
                >
                  <span class="disc-tr-chip disc-tr-chip--jobs">
                    &#10003; {{ agent.track_record.jobs }} {{ trJobsLabel(agent.track_record.jobs) }}
                  </span>
                  <span v-if="agent.track_record.stars" class="disc-tr-chip disc-tr-chip--stars">
                    &#9733; {{ agent.track_record.stars }}
                  </span>
                  <span v-if="agent.track_record.on_time_of > 0" class="disc-tr-chip">
                    {{ agent.track_record.on_time_met }}/{{ agent.track_record.on_time_of }} {{ t('discoveryView.tr.onTime', 'on time') }}
                  </span>
                  <span v-if="agent.track_record.cross_registry > 0" class="disc-tr-chip disc-tr-chip--xreg">
                    &#11041; {{ agent.track_record.cross_registry }} {{ t('discoveryView.tr.crossRegistry', 'cross-registry') }}
                  </span>
                  <span v-if="agent.track_record.disputes > 0" class="disc-tr-chip disc-tr-chip--disputes">
                    {{ agent.track_record.disputes }} {{ t('discoveryView.tr.disputed', 'disputed') }}
                  </span>
                  <span class="disc-tr-more">{{ t('discoveryView.tr.receipts', 'receipts') }} &#9656;</span>
                </div>
              </div>

              <!-- Date -->
              <div class="shrink-0 text-xs nc-text-muted text-right">
                <div>{{ formatRelativeTime(agent.created_at) }}</div>
                <button
                  @click.stop="viewAgentByDID(agent.agent_did || agent.did || agent.id)"
                  class="mt-2 p-1 rounded-sm opacity-0 group-hover:opacity-100 focus-visible:opacity-100 touch:opacity-100 transition-opacity hover:bg-cyan-500/10"
                  title="View Details"
                >
                  <svg class="w-4 h-4 text-cyan-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                      d="M15 12a3 3 0 11-6 0 3 3 0 016 0zM2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/>
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Load More -->
        <div v-if="!embedded && hasMore && !loading" class="text-center mt-8">
          <ReadFailedNotice v-if="loadMoreFailed" dense :retry="loadMore" data-testid="disc-more-failed" />
          <button v-else @click="loadMore" :disabled="loadingMore" class="nc-btn nc-btn-ghost px-6 py-2">
            {{ loadingMore ? 'Loading...' : 'Load More' }}
          </button>
        </div>

      </div>
    </div>

    <!-- Agent Details Modal -->
    <AgentDetailModal
      v-model:show="showDetailsModal"
      :agent-did="selectedAgentId"
      @filter-by-tag="addTag"
    />

    <!-- B10: reusable registry-card viewer (federation strip peers → their card) -->
    <SovereignRegistryCard
      v-model:show="showRegCard"
      :peer-name="regCardPeer"
      :fallback-name="regCardPeer || 'this registry'"
    />

    <!-- §AGENTDISC #188 — receipts drawer: verifiable track record for one agent -->
    <Teleport to="body">
      <div v-if="trackRecordAgent" class="disc-tr-overlay" data-testid="disc-tr-drawer" @click.self="trackRecordAgent = null">
        <div class="disc-tr-modal">
          <div class="disc-tr-head">
            <div>
              <h3 class="disc-tr-title">{{ trackRecordAgent.name }}</h3>
              <div class="disc-tr-sub">{{ t('discoveryView.tr.drawerSub', 'Proven work: registry-attested, verifiable in your browser') }}</div>
            </div>
            <button class="disc-tr-close" :aria-label="t('common.close', 'Close')" @click="trackRecordAgent = null">&#10005;</button>
          </div>
          <TrackRecordPanel :did="trackRecordAgent.did" :max-rows="10" show-ctas show-engage
                            :agent-name="trackRecordAgent.name" @engage="onDrawerEngage" />
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, computed, reactive, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUIStore } from '@/stores/ui'
import { useAuthStore } from '@/stores/auth'
import { usePermissions } from '@/composables/usePermissions'
import { discoveryService } from '@/services/api/discovery'
import { EARNED_TIERS } from '@/services/api/trackRecord'
import type { FederationPeer, NetworkStats, DiscoverFacets } from '@/services/api/discovery'
import { apiClient } from '@/services/api/client'
import { exchangeService, type EquityChip } from '@/services/api/exchangeService'
import Icon from '@/components/Icon.vue'
import AgentDetailModal from '@/components/AgentDetailModal.vue'
import FirmsLane from '@/components/discovery/FirmsLane.vue'
// §DIRFEED — the federated INDEX lane. It renders ONLY where a Directory is configured and the flag is on
// (public registry-config), so this page is byte-unchanged on every node that has never heard of one.
// §DISCPANEL — the index's own bar, beside the federation strip.
import DirectoryStrip from '@/components/discovery/DirectoryStrip.vue'
import BondMaturityBar from '@/components/discovery/BondMaturityBar.vue'
import BondChip from '@/components/discovery/BondChip.vue'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { directoryService } from '@/services/api/directory'
import TrackRecordPanel from '@/components/common/TrackRecordPanel.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import EarnedMarkRing from '@/components/common/EarnedMarkRing.vue'
import EarnedMarkLegend from '@/components/common/EarnedMarkLegend.vue'
import SovereignRegistryCard from '@/components/SovereignRegistryCard.vue'
import UserAvatar from '@/components/common/UserAvatar.vue'
import PeerOrb from '@/components/federation/PeerOrb.vue'
import { useFederationTopology } from '@/composables/useFederationTopology'
import { useI18n } from '@/composables/useI18n'
import { useCurrency } from '@/composables/useCurrency'
import { useFrames } from '@/composables/useFrames'
import { fxService } from '@/services/api/fx'

const { t, tp } = useI18n()
// FX multi-currency: an agent's price is in ITS home-frame currency (may be
// foreign); networkTVL must not sum across currencies. §17.5 [ITEM] / §17.3.
const { localCurrency, currencyForItem, isForeignItem } = useCurrency()
const { localFx } = useFrames()

// ── B8 (2026-06-03) — FX-aware discovery ───────────────────────────────────
// Is FX enabled on THIS (host) registry? Env-authoritative via /teg/fx/rate
// `available` (the same signal the FX desk uses), with the well-known card's
// fees.fx.enabled as a fallback. Decides whether a cross-currency agent is
// payable via FX (badge) or not transactable from here (greyed + hint).
const hostFxEnabled = ref(false)
async function loadHostFx() {
  try {
    const r = await fxService.publicRate()
    if (r && r.available === true) { hostFxEnabled.value = true; return }
  } catch { /* fall through to the well-known card signal */ }
  const fx: any = localFx.value
  hostFxEnabled.value = !!(fx && fx.enabled === true)
}
void loadHostFx()

// Per-agent FX reachability from the viewer's frame:
//   same currency         → { foreign:false }                  → normal card
//   foreign + host FX on  → { foreign:true, via:true,  ccy }   → "via FX" badge
//   foreign + host FX off → { foreign:true, locked:true, ccy } → greyed + hint
function fxStateFor(agent: any): { foreign: boolean; via: boolean; locked: boolean; ccy: string } {
  if (!isForeignItem(agent)) return { foreign: false, via: false, locked: false, ccy: '' }
  const ccy = currencyForItem(agent)
  return { foreign: true, via: hostFxEnabled.value, locked: !hostFxEnabled.value, ccy }
}
function fxHint(agent: any): string {
  return `Cross-currency (${currencyForItem(agent)}) — enable FX on your registry to transact with this agent.`
}

function debounce<T extends (...args: any[]) => any>(func: T, wait: number): T {
  let timeout: ReturnType<typeof setTimeout> | null = null
  return ((...args: Parameters<T>) => {
    if (timeout) clearTimeout(timeout)
    timeout = setTimeout(() => func(...args), wait)
  }) as T
}

const uiStore = useUIStore()

// ── XSS Sanitization ───────────────────────────────────────────────
// Only allow <mark> tags from search highlighting. Strip everything else.
function sanitizeHighlight(html: string | undefined | null): string {
  if (!html) return ''
  // Escape all HTML entities first
  const escaped = html
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
  // Re-allow only <mark> and </mark> tags (used by search highlighting)
  return escaped
    .replace(/&lt;mark&gt;/g, '<mark>')
    .replace(/&lt;\/mark&gt;/g, '</mark>')
}

// ── State ──────────────────────────────────────────────────────────
// §FESUITE (the loading sweep, 2026-10-04): the list starts as LOADING. onMounted awaits the two showcase reads before
// performSearch() runs, so a page that started at false read "not loading, zero results" for that whole wait and drew
// "No agents found" before it knew (a member saw it on every arrival). The skeleton, the stats' dash and the refresh
// button read the same flag; performSearch() clears it when its answer (or its failure) is in.
const loading = ref(true)
const loadingMore = ref(false)
const loadMoreFailed = ref(false)   // §FESUITE (V0576): the last Load More got no page (see loadMore)
/**
 * §LANDINGDISC-2 — the landing page mounts THIS view in `embedded` mode rather than re-implementing a
 * card: the preview shows the real discovery cards with their flare encirclements, provenance badges and
 * the detail modal, capped to `previewLimit`. Everything that is page furniture (hero, both strips, stat
 * tiles, filter rail, the results heading) is gated off; nothing about a card changes.
 */
const props = withDefaults(defineProps<{ embedded?: boolean; previewLimit?: number }>(), {
  embedded: false,
  previewLimit: 6,
})
const embedded = computed(() => props.embedded)

const searchQuery = ref('')
const didQuery = ref('')
const viewMode = ref<'grid' | 'list'>('grid')
const showDetailsModal = ref(false)
const selectedAgentId = ref('')

// §AGENTDISC #188 — receipts drawer state. The track-record endpoints key on the
// AGENT did (agent_did); card_did is a fallback for older mirrors.
const trackRecordAgent = ref<null | { did: string; name: string }>(null)
// §AGENTDISC #191 — why-ranked-here transparency. The breakdown recomputes every
// contribution from the SAME numbers the card shows, with the weights the server
// declared in the response meta — the explanation cannot drift from the ranking.
const rankingMeta = ref<any>(null)
const rankOpenId = ref<string | null>(null)
function toggleRankWhy(agent: any) {
  rankOpenId.value = rankOpenId.value === agent.id ? null : agent.id
}
function rankBreakdown(agent: any): { rows: { label: string; value: string; pts: number }[]; total: number } {
  const w = rankingMeta.value?.weights || {}
  const tr = agent.track_record
  const rows: { label: string; value: string; pts: number }[] = []
  let total = 0
  const push = (label: string, value: string, pts: number) => { rows.push({ label, value, pts: Math.round(pts * 100) / 100 }); total += pts }
  if (tr) {
    push(t('discoveryView.rank.jobs', 'verified jobs'), String(tr.jobs), (w.jobs_ln ?? 2) * Math.log(1 + (tr.jobs || 0)))
    if (tr.stars !== null && tr.stars !== undefined)
      push(t('discoveryView.rank.stars', 'average stars'), String(tr.stars), (w.stars_centered ?? 0.5) * (tr.stars - 3))
    if (tr.last_verified_at) {
      const days = Math.max(0, (Date.now() - new Date(tr.last_verified_at).getTime()) / 86400000)
      push(t('discoveryView.rank.recency', 'recency'), `${Math.round(days)}d`, (w.recency_180d ?? 1) * Math.max(0, 1 - days / 180))
    }
    if (tr.cross_registry)
      push(t('discoveryView.rank.cross', 'cross-registry'), String(tr.cross_registry), (w.cross_capped3 ?? 0.3) * Math.min(tr.cross_registry, 3))
    if (tr.lost_disputes)
      push(t('discoveryView.rank.lost', 'lost disputes'), String(tr.lost_disputes), (w.lost_dispute ?? -1.5) * tr.lost_disputes)
    if (tr.open_disputes)
      push(t('discoveryView.rank.open', 'open disputes'), String(tr.open_disputes), (w.open_dispute ?? -0.75) * tr.open_disputes)
  }
  push(t('discoveryView.rank.reputation', 'reputation'), String(Math.round(agent.reputation_score || 0)),
       (w.reputation_percent ?? 0.01) * Math.min(agent.reputation_score || 0, 100))
  return { rows, total: Math.round(total * 100) / 100 }
}

function trJobsLabel(n: number): string {
  return n === 1 ? t('discoveryView.tr.jobVerified', 'job verified')
    : t('discoveryView.tr.jobsVerified', 'jobs verified')
}
function openTrackRecord(agent: any) {
  const did = agent.agent_did || agent.did
  if (!did) return
  trackRecordAgent.value = { did, name: agent.name || did }
}

// §AGENTDISC #195 — Engage from the drawer = open the full card (the direct line
// surface: endpoint, curl, pricing) for the same agent.
function onDrawerEngage() {
  const a = trackRecordAgent.value
  trackRecordAgent.value = null
  if (a) viewAgentByDID(a.did)
}

// B10 — reusable registry-card viewer (opened from the federation strip peers)
const showRegCard = ref(false)
const regCardPeer = ref<string | null>(null)
function openRegCard(name: string | null) { regCardPeer.value = name; showRegCard.value = true }
const currentOffset = ref(0)
const pageSize = 30
const registryFilter = ref<'all' | 'local' | 'federated'>('all')

// ── Live network data ───────────────────────────────────────────────
const federationPeers = ref<FederationPeer[]>([])

/** §FRAMELIC row 157 — the registry-card fan-out re-inserts a peer under its card's UPPERCASE
 *  name, so `ASIA` (INACTIVE, 0 agents, no mTLS port) sat in the strip beside the real `asia`
 *  (ACTIVE, 11). The strip drew seven chips under a heading that counted six: the count comes
 *  from the index, the chips came from the raw peer list, and nothing reconciled them.
 *
 *  A peer name differing only by case is the SAME registry. Collapse here, once, where the list
 *  is built, preferring the ACTIVE row. Never per-surface, and never by deleting the row: ONLY a
 *  fully-deleted peer_registries row triggers federation_card_gc, which hard-deletes that peer's
 *  mirrored cards. The ghost stays in the database and off the screen. */
function dropCaseGhosts(list: FederationPeer[]): FederationPeer[] {
  const best = new Map<string, FederationPeer>()
  for (const p of list || []) {
    const k = String(p?.name ?? '').toLowerCase()
    const cur = best.get(k)
    if (!cur || (cur.status !== 'ACTIVE' && p.status === 'ACTIVE')) best.set(k, p)
  }
  return [...best.values()]
}
const networkStats = ref<NetworkStats | null>(null)

// §DISCFIX — server facets. `facets` tracks the CURRENT query (drives the
// sidebar counts, which respond to the search like real faceting should);
// `globalFacets` is the first UNfiltered snapshot (drives the federation
// strip's per-peer chips, which are network state, not query state).
const facets = ref<DiscoverFacets | null>(null)
const globalFacets = ref<DiscoverFacets | null>(null)

// ── Filters ────────────────────────────────────────────────────────
const filters = reactive({
  tag: '',
  tags: [] as string[],
  pricing_model: '',
  is_certified: false,
  is_online: false,   // §DISCFIX — now "seen alive in the last 24h" (real liveness)
  bonded_only: false, // §REPBOND — only agents holding a reputation bond
  // §DISCMIX — the gate, made visible. Under REPUTATION_BOND_MODE=enforce this registry REMOVES an unbonded
  // provider from the page, the facets and the counts; nothing on screen said so. This lifts it for the
  // registry's own rows AND for the folded-in index rows, so a person can see what the bond is hiding.
  include_unbonded: false,
  answerable_only: false, // only agents that have described themselves and answer a probe
  // §AGENTDISC #191 — proof-weighted ranking is the browse default: verified
  // outcomes over self-description (server falls back to relevance when unscored).
  sort_by: 'proven' as string,
})

// ── Results ────────────────────────────────────────────────────────
const searchResults = ref<any[]>([])
// §FESUITE: the last search's read failed (the list on screen is not an answer; the empty state must not claim "none")
const readFailed = ref(false)
const totalResults = ref(0)
const hasMore = ref(false)
// §FESUITE: the filters the registry applied to the last search (its applied_filters echo); the unbonded box reads it
const appliedFilters = ref<Record<string, any> | null>(null)
const unbondedRefused = computed(() => !!filters.include_unbonded && appliedFilters.value?.include_unbonded === false)
const suggestions = ref<string[]>([])
const encircledAgents = ref<any[]>([])
// §SHOWCASE-A — the band shows agents carrying an earned mark; on a frame whose guild books are
// empty it falls back to the flare-bearers. Which one is on screen changes what the line under
// the heading may honestly claim, so it is derived from the rows themselves, never assumed.
const encircledAreMarked = computed(() =>
  encircledAgents.value.some((a: any) => Number(a?.track_record?.jobs ?? a?.trackRecord?.jobs ?? 0) > 0))
const showEncircled = ref(true)
const foreignAgents = ref<any[]>([])
// §DISCFIX — filter options are server facets now (the old getFilters() rode
// the 20-second full-corpus fetch). Tags replace the derived pseudo-categories.
const availableFilters = computed(() => {
  const f = facets.value
  return {
    tags: f?.tags || [],
    pricing_models: [
      { model: '', label: 'All', count: f?.total ?? 0 },
      { model: 'free', label: 'Free', count: f?.free ?? 0 },
      { model: 'paid', label: 'Paid', count: f?.paid ?? 0 },
    ],
  }
})

// §pass8 (2026-05-15) — Frame filter. Single-select dropdown with peers
// surfacing in current result set. SUPERSEDED by §pass62.1.
// §pass62.1 (2026-05-21) — Multi-select peer chip-list. Sources peer list
// from useFederationTopology (full federation roster, NOT only peers with
// agents currently in result set — scales as new peers join without traffic).
// Empty selection = "show all" per Commander spec.
const route = useRoute()
const router = useRouter()
const fedTopology = useFederationTopology({ admin: false }) // public topology — Discovery is public

// Set<string> of selected peer names. Empty = show all (no filter applied).
// '__local__' is a reserved member meaning "agents from this local registry".
const selectedFrames = ref<Set<string>>(new Set<string>())

// Full peer roster from topology — used to populate filter chips.
// Each entry: { key, label, isLocal, peer (optional FederatedPeer) }.
interface FrameOption { key: string; label: string; isLocal: boolean; peer: any | null; count: number }

// §DISCFIX — authoritative per-origin counts from the server facets (the old
// page-sum counted the visible slice of a truncated fetch window and read 0
// for every peer). Case-insensitive lookup tolerates display-case drift
// between peer_registries and the origin stamps (the §PEERFIX class).
const facetCountByOrigin = computed<Map<string, number>>(() => {
  const m = new Map<string, number>()
  for (const o of (facets.value?.origins || [])) m.set(o.name.toLowerCase(), o.count)
  return m
})
function originCount(name: string): number {
  return facetCountByOrigin.value.get((name || '').toLowerCase()) ?? 0
}
const localFacetCount = computed(() => originCount('Local'))

/**
 * §NUMALIGN (2026-09-08, his report: "the numbers confusing me. i dont fully understand this").
 *
 * The page carries THREE populations and used to label none of them:
 *   · this list, the peer strip and this filter — `/agent-cards/discover`, which is BOND-GATED;
 *   · the federated-index bar — what each registry PUBLISHES, no bond gate;
 *   · the four stat cards — computed over THIS registry's own database.
 * Measured on EU: 38 / 56 / 56, and the 18 between the first two are entirely system and test
 * agents that hold no reputation bond (`@fx_router`, the canaries, the AGORA gateway, a treasury,
 * two probe desks). Every number was correct. Nothing on screen said they answered different
 * questions, and two of them being equal by accident made it worse.
 *
 * So the filter row now carries BOTH: what this marketplace lists, and what the index says that
 * registry publishes — but only when they DIFFER, because a number repeated twice is noise and a
 * number that appears once is a fact.
 */
/** How many MORE that registry publishes than this bond-gated list shows. 0 when they agree. */
function peerIndexExtra(opt: { key: string; label: string; isLocal?: boolean; count: number }): number {
  const idx = indexCountByPeer.value[(opt.isLocal ? (localRegistryName.value || opt.label) : opt.label).toLowerCase()]
  if (typeof idx !== 'number') return 0
  return Math.max(0, idx - (opt.count || 0))
}

const indexCountByPeer = computed<Record<string, number>>(() => {
  const out: Record<string, number> = {}
  for (const src of (indexStatus.value?.sources || [])) {
    if (src?.name) out[String(src.name).toLowerCase()] = Number(src.agentsIndexed ?? 0)
  }
  return out
})

const availableFrameOptions = computed<FrameOption[]>(() => {
  const options: FrameOption[] = []
  // Local always first
  const localPeer = fedTopology.localRegistry.value
  options.push({
    key: '__local__',
    label: localPeer?.name || 'Local',
    isLocal: true,
    peer: localPeer ? {
      // synthesize a FederatedPeer-like shape so PeerOrb can render it
      id: 0,
      name: localPeer.name,
      peer_type: 'local',
      visual: (localPeer as any).visual ?? null,
    } : null,
    count: localFacetCount.value,
  })
  // Peers from topology — include all, even with count=0
  const seen = new Set<string>(['local'])
  for (const p of fedTopology.allPeers.value) {
    seen.add(p.name.toLowerCase())
    options.push({
      key: p.name,
      label: p.name,
      isLocal: false,
      peer: p,
      count: originCount(p.name),
    })
  }
  // Origins the server counted that the topology doesn't know (a peer synced
  // through an intermediary) — surface them so the user can still filter.
  for (const o of (facets.value?.origins || [])) {
    const low = o.name.toLowerCase()
    if (low === 'local' || seen.has(low)) continue
    options.push({ key: o.name, label: o.name, isLocal: false, peer: null, count: o.count })
  }
  // §DISCFIX P2 — local pinned first, peers by agent count descending.
  const [local, ...peers] = options
  peers.sort((a, b) => (b.count - a.count) || a.label.localeCompare(b.label))
  return [local, ...peers]
})

// §DISCFIX — the origin filter is applied SERVER-side now (performSearch sends
// selectedFrames); this passthrough keeps the template stable.
// ─────────────────────────────────────────────────────────────────────────────
// §DISCMIX (2026-09-06, his word "we need to retire this 2 split discovery … sorting mix all sources") —
// ONE list, three sources, deduplicated:
//   1. the registry's own ranked page (its natives AND the mirrors it syncs) — the only rows you can act on here;
//   2. the cross-currency rescue (B9): foreign-frame agents the ranked page's cap would bury — they used to be
//      a section of their own and are now ordinary rows wearing the purple skin;
//   3. the FEDERATED INDEX: agents on registries this frame does not mirror. His rule, verbatim — "indexed
//      folded in if not already synched otherwise existing, because then you don't need to go to their home to
//      receive their service" — so a row already present locally always wins, and only the rest fold in.
//
// The bond gate applies to the folded rows too, and that is not a detail: under REPUTATION_BOND_MODE=enforce
// this registry's own discovery REMOVES an unbonded provider from the page, the facets and the counts. Folding
// index rows in without the same rule would quietly undo the gate — on this pair it would resurrect 46 of them.
// The Trust filter's "include agents without a bond" lifts it for BOTH sources at once, which is the only
// honest way to show a person what the gate is hiding.
// ─────────────────────────────────────────────────────────────────────────────
function rowKey(a: any): string {
  return String(a?.agent_did || a?.did || a?.id || '').toLowerCase()
}

const indexAgents = ref<any[]>([])
const indexStatus = ref<any>(null)
const indexListings = ref<any[]>([])
const indexAsOf = ref<number | null>(null)
const indexLoading = ref(false)
const indexFailed = ref('')

/** An index row wearing the shape of a discover row, so ONE card renders every source. Every field the card
 *  touches is present — a missing one is not "unknown", it is a crash in a helper. */
function indexRowToAgent(e: any): any {
  const bond = e?.bond && e.bond.status && e.bond.status !== 'none' ? {
    status: e.bond.status, is_bonded: !!e.bond.isBonded, amount: e.bond.amount, currency: e.bond.currency,
    required_amount: null, locked_at: null, matured_at: null, funded_by: null, progress: null,
    source: 'index', registry: e.source,
  } : null
  return {
    id: 'idx:' + e.cardId, did: e.did, agent_did: e.did,
    name: e.name || e.humanReadableId || e.cardId,
    human_readable_id: e.humanReadableId || null,
    description: e.description || null,
    card_data: null, icon_url: null, flare: null, tags: [],
    origin_registry_name: e.source, is_local: false, unlisted: false, is_active: true,
    settlement_currency: e.homeCurrency || null,
    trust_domain: e.home?.trustDomain || null,
    is_paid: false, pricing: null,
    is_bonded: !!e?.bond?.isBonded,
    is_enforced: !!e?.enforcement?.isEnforced,
    reputation: { bond, is_bonded: !!e?.bond?.isBonded, volume: null, transactions: null, eigentrust: null, staked: null },
    reputation_score: null, track_record: null,
    is_live: false, last_active_at: null, last_health: null,
    developer_is_verified: false, is_certified: false,
    created_at: null, updated_at: null,
    __index: true,
    __home: e.home || null,
    __shape: e.shape || null,
  }
}

/** Rows the index knows and this frame does not hold — the only ones worth folding in (his rule). */
/** Index rows this frame does not already hold — before the trust gate. */
const indexNotHere = computed(() => {
  const here = new Set<string>()
  for (const a of searchResults.value) here.add(rowKey(a))
  for (const a of foreignAgents.value) here.add(rowKey(a))
  return indexAgents.value.filter(e => e?.did && !here.has(String(e.did).toLowerCase()))
})

const indexOnlyAgents = computed(() =>
  indexNotHere.value.filter(e => filters.include_unbonded || !!e?.bond?.isBonded).map(indexRowToAgent))

/** How many the bond gate is holding back. On this pair that is the whole index remainder —
 *  a count of 0 folded in reads as "the index found nothing", which is the opposite of true;
 *  what it found is unbonded, and the trust filter is the switch. Say so rather than show a
 *  zero and let it be read as an empty network. */
const indexWithheld = computed(() =>
  filters.include_unbonded ? 0 : indexNotHere.value.filter(e => !e?.bond?.isBonded).length)

/** The cross-currency rescue, minus anything the ranked page already returned. */
const foreignExtras = computed(() => {
  const here = new Set(searchResults.value.map(rowKey))
  return foreignAgents.value.filter(a => !here.has(rowKey(a)))
})

const filteredResults = computed(() => {
  if (searchQuery.value.trim()) return searchResults.value   // a query is the user's own filter; do not pad it
  const all = [...searchResults.value, ...foreignExtras.value, ...indexOnlyAgents.value]
  return props.embedded ? all.slice(0, props.previewLimit) : all
})

// §DISCMIX — the index in ONE call, cached in the tab so the list paints from the last answer instead of
// waiting behind the page's own request queue (the index itself answers in ~35 ms; the wait was the queue).
const INDEX_CACHE_KEY = 'disc.index.snapshot.v1'
async function loadIndex(force = false) {
  if (!directoryDiscoveryEnabled.value) return
  if (!force) {
    try {
      const raw = sessionStorage.getItem(INDEX_CACHE_KEY)
      if (raw) {
        const c = JSON.parse(raw)
        if (c && Array.isArray(c.agents)) {
          indexAgents.value = c.agents; indexStatus.value = c.status; indexListings.value = c.listings || []
          indexAsOf.value = c.at || null
        }
      }
    } catch { /* a tab with storage blocked simply fetches */ }
  }
  indexLoading.value = true
  try {
    const snap = await directoryService.snapshot(directoryUrl.value, 200)
    indexAgents.value = snap.agents; indexStatus.value = snap.status; indexListings.value = snap.listings
    indexAsOf.value = Date.now(); indexFailed.value = ''
    try { sessionStorage.setItem(INDEX_CACHE_KEY, JSON.stringify({ at: indexAsOf.value, ...snap })) } catch { /* ignore */ }
  } catch (e: any) {
    // an unreachable index must not read as an empty network — the rows we already have stay, and it says so
    indexFailed.value = String(e?.message || e || 'unreachable')
  } finally { indexLoading.value = false }
}

/** Where an index-only row is actually served — the index finds, the home decides. */
function openAtHome(agent: any) {
  const base = String(agent?.__home?.publicUrl || '').replace(/\/+$/, '')
  if (!base) return
  window.open(`${base}/#/agent/${encodeURIComponent(agent.agent_did || agent.did || '')}`, '_blank', 'noopener')
}

const lastRefreshedAt = ref<number | null>(null)
const nowTick = ref(Date.now())
// the clock has to die with the view: this is a plain setInterval in setup, so every mount of
// Discovery used to add one more that ran for the life of the tab.
const nowTimer = window.setInterval(() => { nowTick.value = Date.now() }, 15000)
onBeforeUnmount(() => window.clearInterval(nowTimer))
const lastRefreshedAgo = computed(() => {
  if (!lastRefreshedAt.value) return ''
  const s = Math.max(0, Math.round((nowTick.value - lastRefreshedAt.value) / 1000))
  return s < 60 ? tp('discoveryView.agoSeconds', '{n}s ago', { n: s }) : tp('discoveryView.agoMinutes', '{n} min ago', { n: Math.round(s / 60) })
})

/** What the denominator means once the list is a merge: this registry's own matching population
 *  plus everything the other two sources contributed to THIS list. */
const totalShown = computed(() => totalResults.value + foreignExtras.value.length + indexOnlyAgents.value.length)

/**
 * §MARKSURFACES (2026-09-10) — the sentence beside the earned-mark legend.
 *
 * His words were *"we had a ranking display on the avatar man this got compeltly lost"*,
 * and the measurement behind them is the whole reason this line exists: the apex moved to
 * EU on 2026-09-09, EU's guild ledger held ZERO settled orders, so every avatar on the
 * flagship rendered no mark — correctly, and indistinguishably from the feature having
 * been removed. §DISCMIX is my own rule and this surface never had it: a gate that removes
 * everything must name what it withheld.
 *
 * It counts what is ON THE PAGE, because that is what the reader can see. An empty page
 * gets no sentence at all — there is no population to make a claim about, and inventing
 * one would be the same mistake in the other direction.
 */
const earnedMarkCensus = computed<string>(() => {
  const rows = searchResults.value || []
  if (!rows.length) return ''
  const marked = rows.filter((a: any) => Number(a?.track_record?.jobs || 0) > 0).length
  if (marked > 0) {
    return tp('discoveryView.marks.censusSome', '{n} of {of} on this page carry a mark.',
              { n: marked, of: rows.length })
  }
  return t('discoveryView.marks.censusNone',
           'No agent on this page has a verified guild job yet, so none carries a mark. The ladder above is what one looks like.')
})

const mixCounts = computed(() => ({
  page: searchResults.value.length,
  foreign: foreignExtras.value.length,
  index: indexOnlyAgents.value.length,
  withheld: indexWithheld.value,
}))

function toggleFrame(key: string) {
  const next = new Set(selectedFrames.value)
  if (next.has(key)) next.delete(key); else next.add(key)
  selectedFrames.value = next
}

function selectAllFrames() {
  const next = new Set<string>()
  for (const o of availableFrameOptions.value) next.add(o.key)
  selectedFrames.value = next
}

function clearFrames() {
  selectedFrames.value = new Set<string>()
}

// ── URL hydration: ?frames=name1,name2 ──────────────────────
// Mirrors the Federation.vue pattern: hydrate on mount, debounced push back.
// __local__ is encoded as the literal string "__local__" in the URL.
let _hydratingFromUrl = false
let _lastPushedFrames = ''

function hydrateFramesFromUrl() {
  _hydratingFromUrl = true
  try {
    const raw = route.query.frames
    if (typeof raw === 'string' && raw.trim()) {
      const set = new Set<string>()
      for (const name of raw.split(',').map(s => s.trim()).filter(Boolean)) {
        set.add(name)
      }
      selectedFrames.value = set
    }
  } finally {
    _hydratingFromUrl = false
  }
}

const pushFramesToUrl = debounce(() => {
  if (_hydratingFromUrl) return
  const arr = Array.from(selectedFrames.value)
  const value = arr.length ? arr.join(',') : undefined
  const serialized = value || ''
  if (serialized === _lastPushedFrames) return
  _lastPushedFrames = serialized
  const next: any = { ...route.query }
  if (value) next.frames = value; else delete next.frames
  router.replace({ query: next }).catch(() => { /* NavigationDuplicated */ })
}, 250)

watch(selectedFrames, () => {
  pushFramesToUrl()
  // §DISCFIX — origin filtering is server-side now; a chip toggle re-queries
  // (~50ms round-trip, cheap enough to fire per click).
  performSearch()
}, { deep: false })

// Backend returns pricing model labels in English ("All", "Free", "Paid", etc.)
// Map them to i18n keys when known; fall back to the backend label otherwise.
function translatePricingLabel(model: { model: string; label: string }): string {
  const m = (model.model || '').toLowerCase()
  if (m === 'all' || m === '') return t('discoveryView.pricing.all')
  if (m === 'free') return t('discoveryView.pricing.free')
  if (m === 'paid' || m === 'fixed') return t('discoveryView.pricing.paid')
  if (m === 'subscription') return t('discoveryView.pricing.subscription')
  if (m === 'usage_based' || m === 'usage') return t('discoveryView.pricing.usage')
  return model.label
}

// ── Stats — §DISCFIX: every number here is a SERVER aggregate ─────────────
// The strip previously summed the visible page of a truncated fetch window
// (0 on mirror pages, partial everywhere else). Now:
//   Network Agents = DISTINCT agent DIDs across active cards (mirrors of one
//                    agent collapse; forge name-twins stay distinct)
//   Active (24h)   = agents.last_active_at heartbeat, not the is_active flag
//   Paid Services  = local paid listings
//   Network TVL    = the staking ledger's totalValueLocked
// null → '—' while loading; never a fake 0.
const activeAgents24h = computed<number | null>(() =>
  networkStats.value ? networkStats.value.activeAgents24h : null
)
const paidServiceCount = computed<number | null>(() =>
  networkStats.value ? networkStats.value.paidServices : (globalFacets.value ? globalFacets.value.paid : null)
)
const stakingTvl = ref<number | null>(null)

const networkTVL = computed<number | null>(() => stakingTvl.value)

const networkTotalAgents = computed<number | null>(() => {
  if (networkStats.value?.networkAgents) return networkStats.value.networkAgents
  if (globalFacets.value?.total) return globalFacets.value.total
  return networkStats.value ? networkStats.value.totalAgents : null
})

const fmtStat = (v: number | null): string => (v === null ? '—' : v.toLocaleString(appLocale()))

// Federation strip chips — network state from the global (unfiltered) facets.
const localAgentCount = computed(() => {
  const g = globalFacets.value
  if (g) { const l = g.origins.find(o => o.name.toLowerCase() === 'local'); if (l) return l.count }
  return networkStats.value?.localAgents ?? 0
})
// §DISCPANEL — the info popovers on the two bars (the chip number had no explanation on the page).
const { directoryUrl, directoryDiscoveryEnabled } = useRegistryConfig()
const showStripInfo = ref(false)
/** The peers this frame syncs DIRECTLY, so the index bar can mark which of its sources are also mirrored. */
const syncedPeerNames = computed(() => federationPeers.value.filter(p => p.status === 'ACTIVE').map(p => p.name))

/**
 * §DISCPANEL — how a row REACHED this page. Two mechanisms, and they are not interchangeable:
 *  · local — this registry's own agent, in its own database.
 *  · sync  — a mirror the federation sync COPIED here from that peer; it lives in this frame's database and is
 *            as fresh as the last pull cycle.
 * (The federated index's rows carry their own mark in the lane below; nothing on this grid comes from it.)
 */
function provenanceOf(agent: any): { label: string; title: string; kind: 'local' | 'sync' | 'index' } {
  if (agent?.__index) {
    return {
      kind: 'index',
      label: tp('discoveryView.provenance.indexAt', 'index · {r}', { r: agent.origin_registry_name || '?' }),
      title: tp('discoveryView.provenance.indexTitle', 'Seen through the federated index at {r}. This frame does not mirror it, so it is served at its home.', { r: agent.origin_registry_name || '?' }),
    }
  }
  if (agent?.isFederated) {
    return {
      kind: 'sync',
      label: agent.originRegistry || t('discoveryView.provenance.federated', 'federated'),
      title: tp('discoveryView.provenance.syncTitle', 'Mirrored into this frame by federation sync from {r}', { r: agent.originRegistry || '?' }),
    }
  }
  return {
    kind: 'local',
    label: t('discoveryView.provenance.local', 'local'),
    title: t('discoveryView.provenance.localTitle', "This registry's own agent — not a mirror"),
  }
}

// §DISCOTRUST — the HOST REGISTRY's trust, beside the agent's own record.
//
// A discovery card already answers two of the three questions a caller has: who is this agent
// (its name, price, verified jobs, receipts) and where does it live (which registry, which
// currency). The third is the one that decides whether you act: how much does THIS FRAME trust
// the registry serving it. Without it a caller has to go and audit a stranger's history, which
// costs more than most trades are worth.
//
// Two rules this must not break:
//  · The verdict is THIS frame's own, formed from settlements it witnessed. It arrives only for
//    an authenticated caller, so `undefined` here means "not told", never "fine".
//  · A frame does not hold an opinion of itself, so a LOCAL agent gets no badge at all rather
//    than a flattering one. The provenance badge already says `local`.
function registryTrustOf(agent: any): { show: boolean; state: string; short: string; title: string } | null {
  const prov = provenanceOf(agent)
  if (prov.kind === 'local') return null
  const name = (prov.kind === 'index' ? (agent.origin_registry_name || '') : (agent.originRegistry || '')).toLowerCase()
  if (!name) return null
  const peer = federationPeers.value.find(pp => (pp.name || '').toLowerCase() === name)
  // §TRUSTCHAIN: the backend now stamps the host registry's verdict ON the card for an identified
  // caller (developer or agent); prefer it, and keep the per-peer join for older backends.
  const tr: any = agent?.registry_trust || (peer as any)?.trust
  if (!tr || !tr.state) {
    // Not told is its own state. Never render it as an endorsement.
    return { show: true, state: 'untold', short: t('discoveryView.trust.untold', 'trust n/a'),
             title: tp('discoveryView.trust.untoldTitle',
                       "This frame's assessment of {r} is not published to anonymous callers. Sign in to see it.",
                       { r: name }) }
  }
  const pct = (typeof tr.discount === 'number') ? Math.round(tr.discount * 100) + '%' : null
  const shortByState: Record<string, string> = {
    ok: pct ? `${pct}` : t('discoveryView.trust.ok', 'trusted'),
    warn: pct ? `${pct}` : t('discoveryView.trust.warn', 'watch'),
    restricted: t('discoveryView.trust.restricted', 'restricted'),
    suspended: t('discoveryView.trust.suspended', 'suspended'),
    unmeasured: t('discoveryView.trust.unmeasured', 'unmeasured'),
    unavailable: t('discoveryView.trust.unavailable', 'n/a'),
  }
  return {
    show: true,
    state: tr.state,
    short: shortByState[tr.state] || tr.state,
    // The service's own sentence. It never renders a bare prior as a percentage, which is the
    // whole reason `unmeasured` is a state and not a number.
    title: tp('discoveryView.trust.title', '{r} — {l}', { r: name, l: tr.label || tr.state }),
  }
}

function peerChipCount(name: string): number | null {
  const g = globalFacets.value
  if (!g) return null
  const hit = g.origins.find(o => o.name.toLowerCase() === (name || '').toLowerCase())
  return hit ? hit.count : 0
}

// §DISCFIX P2 — strip chips ordered by weight: active peers by agent count
// descending, inactive ones at the tail (the DB order scattered Frame-B/C
// behind random operators).
const sortedFederationPeers = computed(() => {
  return [...federationPeers.value].sort((a, b) => {
    const aAct = a.status === 'ACTIVE' ? 1 : 0
    const bAct = b.status === 'ACTIVE' ? 1 : 0
    if (aAct !== bAct) return bAct - aAct
    return (peerChipCount(b.name) ?? 0) - (peerChipCount(a.name) ?? 0)
  })
})

const lastSyncAgo = computed(() => {
  const ts = networkStats.value?.lastGlobalSync
  if (!ts) return ''
  const diff = Date.now() - new Date(ts).getTime()
  if (!Number.isFinite(diff) || diff < 0) return ''
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'synced just now'
  if (mins < 60) return `synced ${mins}m ago`
  return `synced ${Math.floor(mins / 60)}h ago`
})

// The REAL local registry name (was a hardcoded "Registry-A" label that showed on
// every registry's Discovery view — a legacy artifact). Sourced from the same
// federation-topology local node the filter options use. [Commander 2026-06-07]
const localRegistryName = computed(() =>
  (fedTopology.localRegistry.value as any)?.name || 'This registry'
)

// ── Init ────────────────────────────────────────────────────────────
onMounted(async () => {
  // §pass62.1 — hydrate frame filter from ?frames= BEFORE first search so the
  // initial render matches Commander's intent when navigating from drawer links.
  hydrateFramesFromUrl()
  // B9 — showcases are tiny, fast server-filtered calls. AWAIT them first so they
  // paint before the heavy main browse fetch (which on a 12k-card frame downloads
  // megabytes + parses thousands of cards, blocking the event loop). This makes
  // the encircled + cross-currency rows appear deterministically on every frame.
  await Promise.all([loadEncircledAgents(), loadForeignAgents()])
  // §DISCMIX — the index paints from the tab's cache immediately and refreshes without being awaited, so it
  // never queues behind the heavy browse fetch (his "it took like a very long time to load").
  // the index lane and the federation topology are page furniture; a preview does not pay for them
  if (!props.embedded) void loadIndex()
  // equity chips — fire FIRST + independent of the heavy browse fetch. Gating
  // this cheap call behind `await Promise.all([performSearch()…])` made it land
  // right at the render window on big frames → chips intermittently absent.
  exchangeService.equityByDid().then(m => { equityByDid.value = m }).catch(() => {})
  await Promise.all([
    performSearch(),
    ...(props.embedded ? [] : [
      loadNetworkData(),
      fedTopology.fetchTopology().catch(() => { /* public-only; ignore */ }),
    ]),
  ])
  // §DISCMIX polish — stamp the freshness clock HERE too, not only in refreshData(). It was
  // written for the button and read by the hero, so on arrival `lastRefreshedAt` was null, the
  // `v-if` hid the line, and the page he asked to "show a refresh timer" on showed one only
  // after you pressed Refresh — the one moment you already know how fresh it is. Measured null
  // on a real load before this.
  lastRefreshedAt.value = Date.now()
})

// ── Methods ────────────────────────────────────────────────────────

async function loadNetworkData() {
  // §DISCPUBLIC / §EXPLORESTRIP — the peer list used to be an ADMIN read only, so a visitor got a 401
  // and a red console line; skipping it for them fixed the noise and BROKE THE STRIP, on /explore and
  // on any member's refresh (the auth store has not hydrated when this runs, so `authed` read false for
  // them too — his report: "on refresh on /explore the registry card strip doesnt show the registries").
  // The service now reads the PUBLIC federation table for everyone and layers the admin list on top when
  // a session produces one, so the flag below widens the result and can no longer be the thing that
  // empties it.
  // §FESUITE: the admin layer is an admin_federation read; every other member asked it and got 403 on each visit.
  // Only someone the rail would answer asks it (the public table is everyone's base either way).
  const authed = !!useAuthStore().isAuthenticated && usePermissions().can('federation')
  const [stats, peers, staking] = await Promise.allSettled([
    discoveryService.fetchNetworkStats(),
    discoveryService.fetchFederationPeers({ authed }),
    apiClient.get('/staking/global-stats'),
  ])
  if (stats.status === 'fulfilled') networkStats.value = stats.value
  if (peers.status === 'fulfilled') federationPeers.value = dropCaseGhosts(peers.value)
  if (staking.status === 'fulfilled') {
    const tvl = parseFloat(staking.value?.data?.totalValueLocked ?? '')
    if (Number.isFinite(tvl)) stakingTvl.value = tvl
  }
}

async function loadEncircledAgents() {
  // Commander 2026-06-03 — "Distinguished Agents" = agents bearing an
  // encirclement flare (replaces the old "featured" paid/reputation grid).
  // B9: server-filtered, so it's complete even on a 12k-card frame.
  try {
    encircledAgents.value = await discoveryService.getEncircledAgents(24)
  } catch { /* expected */ }
}

async function loadForeignAgents() {
  // B9 (2026-06-03) — "Cross-currency Agents": agents on a different-currency
  // frame. Server-filtered so Frame A surfaces its foreign agents past the cap.
  try {
    foreignAgents.value = await discoveryService.getForeignAgents(24)
  } catch { /* expected */ }
}

// §DISCFIX — assemble the /discover request from the view state. The registry
// radio (all/local/federated) and the peer multi-select both collapse into the
// server's `origins` list; '__local__' is the reserved local token.
function buildDiscoverParams(offset: number) {
  let origins: string[] = []
  if (selectedFrames.value.size > 0) {
    origins = Array.from(selectedFrames.value).map(k => k === '__local__' ? 'local' : k)
  } else if (registryFilter.value === 'local') {
    origins = ['local']
  } else if (registryFilter.value === 'federated') {
    origins = availableFrameOptions.value.filter(o => !o.isLocal).map(o => o.key)
  }
  const sortMap: Record<string, string> = { created: 'newest' }
  return {
    q: searchQuery.value,
    origins,
    pricing: (filters.pricing_model === 'paid' || filters.pricing_model === 'free') ? filters.pricing_model as ('paid' | 'free') : '',
    tag: filters.tag,
    verified_only: filters.is_certified,
    active_24h: filters.is_online,
    bonded_only: filters.bonded_only,
    include_unbonded: filters.include_unbonded || undefined,
    answerable_only: filters.answerable_only || undefined,
    sort: sortMap[filters.sort_by] || filters.sort_by,
    limit: pageSize,
    offset,
  }
}

// §REPBOND — the chip's title: status, maturity progress, earned volume — from the block the
// registry returned (local truth, or what the home registry signed onto a mirrored card).
let _searchSeq = 0
async function performSearch() {
  loading.value = true
  currentOffset.value = 0
  loadMoreFailed.value = false
  const seq = ++_searchSeq
  try {
    const response = await discoveryService.discover(buildDiscoverParams(0))
    if (seq !== _searchSeq) return  // a newer keystroke superseded this response
    readFailed.value = false
    searchResults.value = response.results
    totalResults.value = response.total
    hasMore.value = response.has_more
    facets.value = response.facets
    rankingMeta.value = (response as any).ranking || null
    appliedFilters.value = response.applied
    suggestions.value = []
    // First clean (unfiltered, query-less) snapshot feeds the federation strip.
    const unfiltered = !searchQuery.value.trim() && selectedFrames.value.size === 0
      && registryFilter.value === 'all' && !filters.pricing_model && !filters.tag
      && !filters.is_certified && !filters.is_online
    if (unfiltered || !globalFacets.value) globalFacets.value = response.facets
  } catch (error) {
    if (seq !== _searchSeq) return
    uiStore.showError('Search Failed', 'Unable to search agents. Please try again.')
    readFailed.value = true
    searchResults.value = []
    totalResults.value = 0
    hasMore.value = false
    appliedFilters.value = null
  } finally {
    if (seq === _searchSeq) loading.value = false
  }
}

// §FESUITE (V0576): the offset moved BEFORE the read and a failure was swallowed, so a failed Load More did nothing
// visible and the next press asked for the page after the one that never arrived. The offset moves only with the
// page that answered; a failure says so (Try again asks the same page); a newer search drops a late page.
async function loadMore() {
  loadingMore.value = true
  loadMoreFailed.value = false
  const seq = _searchSeq
  const offset = currentOffset.value + pageSize
  try {
    const response = await discoveryService.discover(buildDiscoverParams(offset))
    if (seq !== _searchSeq) return   // a newer search replaced the list this page belonged to
    currentOffset.value = offset
    searchResults.value.push(...response.results)
    hasMore.value = response.has_more
  } catch {
    if (seq === _searchSeq) loadMoreFailed.value = true
  } finally {
    loadingMore.value = false
  }
}

function lookupDID() {
  if (!didQuery.value) return
  selectedAgentId.value = didQuery.value
  showDetailsModal.value = true
  didQuery.value = ''
}

function viewAgentByDID(idOrDid: string) {
  // §FLARESHOP (2026-08-16): call sites now pass the DID FIRST (they used to
  // pass `agent.id`, the card UUID). The modal resolves its DID-dependent
  // sections — the proven-work panel and the signed A2A card link — from what
  // it is opened with, and the PUBLIC /agent-cards/{id} response carries no
  // agent_did at all (verified on both the by-DID and by-UUID routes), so a
  // UUID left those sections with nothing DID-shaped to stand on. The discover
  // rows always know the DID; hand it over.
  selectedAgentId.value = idOrDid
  showDetailsModal.value = true
}

// §V0064 P2 — AGORA equity chip: did→equity for agents whose org is listed on
// THIS venue (equity-map). Empty on dark venues → no chips render.
const equityByDid = ref<Record<string, EquityChip>>({})
function equityFor(agent: any): EquityChip | null {
  const did = agent?.did || agent?.id
  return (did && equityByDid.value[did]) || null
}
function goToStock(chip: EquityChip) {
  router.push({ path: '/agora/listings', query: { sym: chip.symbol } })
}

// console-only diagnostic (house style — cf. __gmReg/__gccDbg): inspect the
// equity-chip resolution against the rendered grid. window.__discEqDbg()
;(window as any).__discEqDbg = () => ({
  equitySize: Object.keys(equityByDid.value).length,
  equityKeys: Object.keys(equityByDid.value),
  firstCardDid: filteredResults.value[0]?.did,
  matched: filteredResults.value.filter((a: any) => equityFor(a)).map((a: any) => ({ did: a.did, sym: equityFor(a)?.symbol })),
})

const handleSearch = debounce(() => { performSearch() }, 300)

function applyFilters() { performSearch() }

function toggleView() { viewMode.value = viewMode.value === 'grid' ? 'list' : 'grid' }

function addTag(tag: string) {
  if (!filters.tags.includes(tag)) { filters.tags.push(tag); applyFilters() }
}

function clearAllFilters() {
  searchQuery.value = ''
  registryFilter.value = 'all'
  selectedFrames.value = new Set<string>()  // §pass62.1 — reset multi-select
  filters.tag = ''
  filters.tags = []
  filters.pricing_model = ''
  filters.is_certified = false
  filters.is_online = false
  filters.sort_by = 'proven'
  performSearch()
}

async function refreshData() {
  discoveryService.clearCache()
  globalFacets.value = null  // let the next unfiltered search re-snapshot the strip
  await Promise.all([performSearch(), loadNetworkData()])
  await Promise.all([loadEncircledAgents(), loadForeignAgents(), loadIndex(true)])
  lastRefreshedAt.value = Date.now()
  uiStore.showSuccess('Refreshed', 'Agent data refreshed from this registry and the federated index')
}

// ── Helpers ────────────────────────────────────────────────────────

function reputationColor(score: number): string {
  if (score >= 60) return 'text-cyan-400'
  if (score >= 40) return 'text-green-400'
  if (score >= 20) return 'text-yellow-400'
  return 'nc-text-muted'
}

function reputationBarClass(score: number): string {
  if (score >= 60) return 'disc-rep-fill--cyan'
  if (score >= 40) return 'disc-rep-fill--green'
  if (score >= 20) return 'disc-rep-fill--yellow'
  return 'disc-rep-fill--dim'
}

function reputationDot(score: number): string {
  if (score >= 60) return 'bg-cyan-400'
  if (score >= 40) return 'bg-green-400'
  if (score >= 20) return 'bg-yellow-400'
  return 'bg-gray-500'
}

function formatAVT(amount: number | null): string {
  if (amount === null) return '—'
  if (!amount || amount === 0) return `0 ${localCurrency.value}`
  if (amount >= 1_000_000) return `${(amount / 1_000_000).toFixed(2)}M ${localCurrency.value}`
  if (amount >= 1_000) return `${(amount / 1_000).toFixed(1)}K ${localCurrency.value}`
  return `${amount} ${localCurrency.value}`
}

// §DISCFIX — honest trust labels. Before: reputation came only from the
// viewer's OWN /developers/me/agents (name-matched), so every foreign card
// showed score 0 → "New" — a 4-month-old agent badged as newborn. Now the
// server joins agents.reputation_score per card; unscored-but-old agents say
// "Unranked", and "New" is reserved for genuinely young ones (<30 days).
// §SHOWCASE-A (2026-09-10) — "UNRANKED" MUST NOT SIT NEXT TO A SOVEREIGN MARK.
//
// His report on the Frame-A explore page: *"not a single ranked agents in sight."* Measured: the
// cards said `Unranked` for agents wearing a seven-line Sovereign collar with 251 verified guild
// jobs and a locked reputation bond, because this chip reads ONLY `agents.reputation_score` —
// the EigenTrust projection, which is trust-weighted TRANSFER VOLUME and is normalised against
// the busiest agent on the frame. A registry that has attested 251 settled engagements for an
// agent is not entitled to call it unranked; it simply had not been asked the other question.
//
// The two numbers stay DISTINCT and the chip says which one it is showing — they are different
// facts and conflating them would be the §MARKSURFACES mistake in a label:
//   `Trust 128`        EigenTrust over transaction flow
//   `Sovereign · 251`  settled guild work with receipts, from this registry's own book
// Nothing here is invented: both come from the row the server already sends.
function trustLabel(agent: any): string {
  const score = Number(agent?.reputation_score || 0)
  if (score > 0) return `Trust ${score.toFixed(0)}`
  const jobs = Number(agent?.track_record?.jobs || 0)
  if (jobs > 0) {
    const step = EARNED_TIERS.find(t => jobs >= t.min)
    if (step) return `${step.label} · ${jobs}`
  }
  const created = agent?.created_at ? new Date(agent.created_at).getTime() : 0
  if (created && (Date.now() - created) < 30 * 86400000) return 'New'
  return 'Unranked'
}

/** True when the chip is showing LEDGER-EARNED rank rather than an EigenTrust score, so the
 *  colour can follow the mark's palette instead of the reputation one. */
function trustIsEarned(agent: any): boolean {
  return !Number(agent?.reputation_score || 0) && Number(agent?.track_record?.jobs || 0) > 0
}

// Colors that follow the honest label: scored → reputation palette; New →
// soft cyan (fresh, not suspicious); Unranked → muted.
function trustColor(agent: any): string {
  const s = Number(agent?.reputation_score || 0)
  if (s > 0) return reputationColor(s)
  if (trustIsEarned(agent)) return 'disc-trust-earned'
  return trustLabel(agent) === 'New' ? 'text-cyan-300' : 'nc-text-muted'
}
function trustDotCls(agent: any): string {
  const s = Number(agent?.reputation_score || 0)
  if (s > 0) return reputationDot(s)
  if (trustIsEarned(agent)) return 'disc-trust-earned-dot'
  return trustLabel(agent) === 'New' ? 'bg-cyan-300' : 'bg-gray-500'
}

// Liveness badge (grid + list cards). Three honest states:
//   local + heartbeat <24h  → live (green)
//   local + no heartbeat    → idle (gray)
//   federated (no local liveness data) → null → no badge at all
function liveState(agent: any): { label: string; cls: string; dot: string; title: string } | null {
  if (agent?.is_live) {
    return { label: 'live', cls: 'disc-badge-active', dot: 'bg-green-400', title: 'Heartbeat seen in the last 24 hours' }
  }
  if (agent?.liveness_known || (!agent?.isFederated && agent?.last_active_at !== undefined)) {
    if (!agent?.isFederated) return { label: 'idle', cls: 'disc-badge-inactive', dot: 'bg-gray-500', title: 'No heartbeat in the last 24 hours' }
  }
  return null
}

function formatRelativeTime(dateString: string): string {
  if (!dateString) return t('common.unknown')
  const diff = Date.now() - new Date(dateString).getTime()
  const days = Math.floor(diff / 86400000)
  const hours = Math.floor(diff / 3600000)
  const mins = Math.floor(diff / 60000)
  if (days > 0) return `${days}d ago`
  if (hours > 0) return `${hours}h ago`
  if (mins > 0) return `${mins}m ago`
  return 'Just now'
}

function showAgentMenu(agent: any) {}
</script>

<style scoped>
/* ── Federation network strip ─────────────────────────────── */
/* §2026-06-29 search-bar polish — premium glowing input (replaces the flat blocky box) */
.disc-search-input {
  background: rgba(8, 13, 24, 0.82);
  border: 1px solid rgba(120, 140, 170, 0.20);
  border-radius: 0.7rem;
  color: var(--nc-text-primary, #e7eef7);
  transition: border-color .18s ease, box-shadow .18s ease, background .18s ease;
}
.disc-search-input::placeholder { color: rgba(140, 155, 180, 0.5); }
.disc-search-input:focus {
  outline: none;
  border-color: rgba(34, 211, 238, 0.65);
  background: rgba(10, 16, 30, 0.92);
  box-shadow: 0 0 0 3px rgba(34, 211, 238, 0.13), 0 8px 26px -12px rgba(34, 211, 238, 0.45);
}
.disc-search-icon { opacity: .7; }

.disc-net-strip {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: rgba(var(--nc-primary-rgb),0.04);
  border: 1px solid rgba(var(--nc-primary-rgb),0.12);
  border-radius: 8px;
  overflow-x: auto;
}

.disc-net-node {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  flex-shrink: 0;
}

.disc-net-local {
  background: rgba(0,230,118,0.08);
  border: 1px solid rgba(0,230,118,0.25);
  color: #00e676;
}

.disc-net-peer--active {
  background: rgba(var(--nc-primary-rgb),0.08);
  border: 1px solid rgba(var(--nc-primary-rgb),0.25);
  color: rgba(var(--nc-primary-rgb),0.9);
}

.disc-net-peer--inactive {
  background: rgba(100,100,100,0.08);
  border: 1px solid rgba(100,100,100,0.2);
  color: rgba(150,150,150,0.8);
}

.disc-net-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.disc-net-dot--green { background: #00e676; box-shadow: 0 0 6px #00e676; animation: discPulse 2s ease-in-out infinite; }
.disc-net-dot--cyan  { background: var(--nc-primary); box-shadow: 0 0 6px var(--nc-primary); animation: discPulse 2s ease-in-out infinite 0.5s; }
.disc-net-dot--gray  { background: #666; }

@keyframes discPulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.disc-net-label { font-weight: 700; }
.disc-net-count { font-size: 10px; opacity: 0.7; }

/* §DISCFIX — honest-liveness affordances */
.disc-live-dot {
  display: inline-block;
  width: 7px; height: 7px; border-radius: 50%;
  background: #00e676;
  box-shadow: 0 0 6px rgba(0,230,118,0.8);
  animation: discPulse 2s ease-in-out infinite;
}
.disc-dot-pulse { animation: discPulse 2s ease-in-out infinite; box-shadow: 0 0 5px rgba(0,230,118,0.7); }
/* §DISCPANEL (2026-09-06, his "the boxes look trash") — the four stat boxes, the search row and the filter
   sidebar were the page's only surfaces NOT built in the house language: the first two passed NeuralCard a
   `flat` variant that existed nowhere (fixed in NeuralCard.vue) and the sidebar used the legacy grey
   `nc-bg-surface` + a grey border. Design_Language.md §3 is the stat tile; §2 is the panel. */
.disc-stat-card {
  border-radius: 8px !important;
  background: rgba(var(--nc-primary-rgb), 0.03);
  transition: border-color .2s ease, background .2s ease;
}
.disc-stat-card:hover { border-color: rgba(var(--nc-primary-rgb), 0.4); background: rgba(var(--nc-primary-rgb), 0.05); }

.disc-side-panel {
  background:
    linear-gradient(168deg, rgba(255, 255, 255, 0.025), rgba(255, 255, 255, 0) 60%),
    rgba(var(--nc-primary-rgb), 0.035);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  border-radius: 12px;
  backdrop-filter: blur(9px) saturate(1.05);
  -webkit-backdrop-filter: blur(9px) saturate(1.05);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03), 0 12px 32px -22px rgba(0, 0, 0, 0.8);
}
.disc-side-panel:hover { border-color: rgba(var(--nc-primary-rgb), 0.26); }

/* the (i) and its popover — one shape, used by this bar and the index bar below it */
.disc-info-btn {
  width: 16px; height: 16px; line-height: 14px; border-radius: 50%; font-size: 10px; font-weight: 700;
  color: var(--nc-primary, #22d3ee); background: rgba(var(--nc-primary-rgb), 0.1);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.35); cursor: pointer; flex-shrink: 0;
}
.disc-info-btn:hover { background: rgba(var(--nc-primary-rgb), 0.2); }
.disc-info-pop {
  position: absolute; right: 8px; top: calc(100% + 6px); z-index: 40; max-width: 470px;
  padding: 10px 12px; font-size: 11px; line-height: 1.5;
  background: linear-gradient(168deg, rgba(255,255,255,0.03), rgba(255,255,255,0) 60%), rgba(8, 13, 24, 0.96);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.28); border-radius: 12px;
  box-shadow: 0 18px 42px -20px rgba(0,0,0,0.9);
}
.disc-info-pop p { margin: 0 0 6px; }
.disc-info-pop p:last-child { margin-bottom: 0; }
.disc-info-h { font-weight: 700; color: var(--nc-primary, #22d3ee); }
.disc-info-dim { opacity: .7; }

/* §DISCPANEL — HOW a row reached this page (his ask). `local` = this registry's own; `⬡ <peer>` = a mirror
   the federation sync copied here. The index's rows carry their own mark, in the lane below. */
.disc-prov-badge {
  font-size: 9px; padding: 1px 5px; border-radius: 3px; white-space: nowrap;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.28); background: rgba(var(--nc-primary-rgb), 0.08);
  color: var(--nc-primary, #22d3ee);
}
.disc-prov-badge--local { border-color: rgba(0, 230, 118, 0.28); background: rgba(0, 230, 118, 0.08); color: #00e676; }
/* §DISCOTRUST — the host registry's verdict. Deliberately quieter than the agent's own marks:
   it qualifies the card, it is not the headline. Every state has its own colour INCLUDING the
   two that are not verdicts (unmeasured, untold), because rendering "no evidence" in the same
   grey as "fine" is how a prior gets read as an endorsement. */
.disc-regtrust {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 1px 6px; border-radius: 999px; font-size: 10px; line-height: 15px;
  border: 1px solid rgba(255,255,255,0.14); background: rgba(255,255,255,0.04);
  color: var(--nc-text-muted, #9aa4b2); white-space: nowrap; font-variant-numeric: tabular-nums;
}
.disc-regtrust-dot { width: 5px; height: 5px; border-radius: 50%; background: currentColor; flex: 0 0 5px; }
.disc-regtrust--ok         { border-color: rgba(0,230,118,0.30);  background: rgba(0,230,118,0.09);  color: #00e676; }
.disc-regtrust--warn       { border-color: rgba(255,193,7,0.34);  background: rgba(255,193,7,0.10);  color: #ffc107; }
.disc-regtrust--restricted { border-color: rgba(255,112,67,0.36); background: rgba(255,112,67,0.11); color: #ff7043; }
.disc-regtrust--suspended  { border-color: rgba(244,67,54,0.40);  background: rgba(244,67,54,0.12);  color: #ef5350; }
.disc-regtrust--unmeasured { border-color: rgba(120,144,180,0.34); background: rgba(120,144,180,0.10); color: #90a4c4; }
.disc-regtrust--untold,
.disc-regtrust--unavailable { border-color: rgba(130,130,140,0.28); background: rgba(130,130,140,0.08); color: #8b8f99; }
.disc-prov-badge--index { border-color: rgba(160, 130, 220, 0.34); background: rgba(160, 130, 220, 0.10); color: #b39ddb; }

/* §DISCPANEL — the hero (Design_Language.md §4: eyebrow chip, H1, lead) and a refresh that reports itself. */
.disc-hero { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 14px; flex-wrap: wrap; }
.disc-eyebrow {
  display: inline-flex; align-items: center; gap: 6px; margin-bottom: 8px;
  font: 700 10px/1 var(--nc-font-mono, ui-monospace, monospace); text-transform: uppercase; letter-spacing: .1em;
  color: var(--nc-primary, #22d3ee); padding: 4px 10px; border-radius: 12px;
  background: rgba(var(--nc-primary-rgb), 0.08); border: 1px solid rgba(var(--nc-primary-rgb), 0.25);
}
.disc-eyebrow-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--nc-primary, #22d3ee); animation: disc-dot-pulse 2.4s ease-in-out infinite; }
.disc-hero-h1 { margin: 0; font-size: 28px; font-weight: 800; letter-spacing: -0.01em; color: var(--nc-text-primary, #e7eef7); }
.disc-hero-lead { margin: 6px 0 0; font-size: 13px; color: var(--nc-text-muted, #8b9bb4); max-width: 62ch; }
.disc-hero-actions { display: flex; align-items: center; gap: 10px; padding-top: 4px; }
.disc-hero-asof { font-size: 11px; opacity: .65; font-variant-numeric: tabular-nums; }
.disc-refresh {
  display: inline-flex; align-items: center; gap: 7px; padding: 7px 14px; border-radius: 8px; font-size: 12px; font-weight: 600;
  color: var(--nc-primary, #22d3ee); background: rgba(var(--nc-primary-rgb), 0.12);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.35); transition: background .18s ease, border-color .18s ease, transform .12s ease;
}
.disc-refresh:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb), 0.2); border-color: rgba(var(--nc-primary-rgb), 0.5); }
.disc-refresh:active:not(:disabled) { transform: translateY(1px); }
.disc-refresh:disabled { opacity: .55; cursor: default; }

/* the strip's popover, anchored OUTSIDE the scrolling bar */
.disc-strip-pop-anchor { position: relative; height: 0; }
.disc-info-pop--strip { top: 4px; }

/* §NUMALIGN (2026-09-08) — the scope word on a stat card, and the index delta on a filter row.
   Both exist because three different populations were being read as one. */
.disc-stat-scope {
  margin-left: 5px; font-size: 9px; letter-spacing: .1em; text-transform: uppercase;
  opacity: .45; border: 1px solid rgba(var(--nc-primary-rgb), 0.22); border-radius: 4px; padding: 0 4px;
}
.disc-ff-idx {
  margin-left: 4px; font-size: 10px; font-variant-numeric: tabular-nums;
  color: var(--nc-primary, #22d3ee); opacity: .7; cursor: help;
}

/* §DISCMIX — the mix line and the two card skins */
.disc-mix-line { font-size: 11px; opacity: .7; margin-bottom: 10px; font-variant-numeric: tabular-nums; }
.disc-mix-more {
  margin-left: 8px; font-size: 11px; font-weight: 600; color: var(--nc-primary, #22d3ee);
  background: none; border: 0; padding: 0; cursor: pointer; text-decoration: underline; text-underline-offset: 2px;
}
.disc-mix-more:hover { opacity: .8; }
.disc-mix-warn { margin-left: 8px; color: #ff6b6b; opacity: .9; }
.disc-filter-group { padding-top: 4px; border-top: 1px solid rgba(var(--nc-primary-rgb), 0.12); }
/* §MARKSURFACES — the earned-mark census sentence. Quiet by design: it is context for
   the legend above it, not a control. */
/* §SHOWCASE-A — the trust chip when it is showing LEDGER-EARNED rank, not an EigenTrust score.
   Deliberately the mark's gold rather than the reputation palette: the two must not be read as
   the same number. */
.disc-trust-earned { color: rgb(212 175 92); }
.disc-trust-earned-dot { background: rgb(212 175 92); }
.disc-mark-census {
  margin: -6px 0 10px; font-size: 0.68rem; line-height: 1.35;
  color: rgb(var(--nc-text-muted-rgb, 148 163 184)); opacity: 0.85;
}
/* his correction: KEEP the purple for cross-currency agents — as a skin on the standard card, same size */
.disc-agent-card--fx {
  background:
    linear-gradient(168deg, rgba(255,255,255,0.07), rgba(255,255,255,0.02) 46%, rgba(255,255,255,0.004) 100%),
    linear-gradient(135deg, rgba(111,66,193,0.14), rgba(214,40,40,0.07)),
    rgba(10, 14, 24, 0.45);
  border-color: rgba(111, 66, 193, 0.32);
}
.disc-agent-card--fx:hover { border-color: rgba(111, 66, 193, 0.5); box-shadow: 0 4px 20px rgba(111, 66, 193, 0.14); }
/* a row this frame does not mirror: quieter, and it opens elsewhere */
.disc-agent-card--index { border-style: dashed; border-color: rgba(160, 130, 220, 0.34); }
.disc-agent-card--index:hover { border-color: rgba(160, 130, 220, 0.55); }
.disc-stat-ico { opacity: .55; flex-shrink: 0; }

.disc-net-badge-active {
  font-size: 9px; padding: 1px 5px; border-radius: 3px;
  background: rgba(0,230,118,0.12); border: 1px solid rgba(0,230,118,0.3); color: #00e676;
}
.disc-net-badge-inactive {
  font-size: 9px; padding: 1px 5px; border-radius: 3px;
  background: rgba(100,100,100,0.1); border: 1px solid rgba(100,100,100,0.2); color: #888;
}

.disc-net-line {
  flex: 1;
  height: 1px;
  background: rgba(var(--nc-primary-rgb),0.15);
  position: relative;
  min-width: 30px;
  overflow: hidden;
}
.disc-net-pulse {
  position: absolute;
  top: 0; left: -100%;
  width: 60%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(var(--nc-primary-rgb),0.6), transparent);
  animation: discFlow 2.5s linear infinite;
}
@keyframes discFlow {
  from { left: -60%; }
  to { left: 160%; }
}

.disc-net-spacer { flex: 1; }
.disc-net-health { flex-shrink: 0; display: flex; align-items: center; }

/* ── Reputation bar ───────────────────────────────────────── */
.disc-rep-bar {
  height: 2px;
  background: rgba(255,255,255,0.06);
  border-radius: 1px;
  overflow: hidden;
}
.disc-rep-fill {
  height: 100%;
  border-radius: 1px;
  transition: width 0.6s ease;
}
.disc-rep-fill--cyan   { background: linear-gradient(90deg, var(--nc-primary), #00e676); box-shadow: 0 0 4px rgba(var(--nc-primary-rgb),0.5); }
.disc-rep-fill--green  { background: linear-gradient(90deg, #00b894, #00e676); }
.disc-rep-fill--yellow { background: linear-gradient(90deg, #fdcb6e, #e17055); }
.disc-rep-fill--dim    { background: rgba(150,150,150,0.3); }

/* ── Agent cards ──────────────────────────────────────────── */
/* §pass8 (2026-05-15) — Avatar slot in Discovery card. UserAvatar handles
   its own internal sizing via size="md" (36px); flex-shrink prevents the
   name column from squeezing the circle. */
.disc-card-avatar { flex-shrink: 0; }

/* §pass18 (2026-05-16) — Polished card: hover lift, gradient inner glow, top-edge
   accent that lights up on hover, smoother shadow transition. The card now
   reads as a "premium tile" rather than a flat row. */
/* §2026-06-07 v2j — legacy grey #131825 (var(--nc-surface)) → DESIGN-LANGUAGE
   house card (subtle primary tint + sheen + hairline + blur). See
   PRODUCTION_DOCS/03_SERVICES/Frontend/Design_Language.md. (Commander) */
.disc-agent-card {
  position: relative;
  /* §2026-06-07 v2k — VISIBLE premium frosted glass (v2j tint was too faint —
     read identical to the old grey). Strong top sheen + clear border + elevation. */
  background:
    linear-gradient(168deg, rgba(255,255,255,0.09), rgba(255,255,255,0.025) 46%, rgba(255,255,255,0.004) 100%),
    rgba(10, 14, 24, 0.45);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.24);
  border-radius: 14px;
  padding: 16px;
  backdrop-filter: blur(16px) saturate(1.12);
  -webkit-backdrop-filter: blur(16px) saturate(1.12);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.08), 0 20px 46px -24px rgba(0,0,0,0.95);
  transition: border-color 0.22s ease, box-shadow 0.22s ease, transform 0.22s ease, background 0.22s ease;
  overflow: hidden;
}
.disc-agent-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
  background: linear-gradient(90deg, transparent 0%, rgba(var(--nc-primary-rgb), 0.85) 50%, transparent 100%);
  opacity: 0;
  transition: opacity 0.22s ease;
  pointer-events: none;
}
.disc-agent-card:hover {
  border-color: rgba(var(--nc-primary-rgb),0.55);
  box-shadow: 0 16px 40px -14px rgba(var(--nc-primary-rgb),0.28), 0 0 0 1px rgba(var(--nc-primary-rgb), 0.14) inset, inset 0 1px 0 rgba(255,255,255,0.10);
  transform: translateY(-3px);
  /* §2026-06-29 — keep the frosted glass on hover (was flattening to a faint
     gradient); layer a faint cyan wash over the sheen instead of replacing it. */
  background:
    linear-gradient(168deg, rgba(255,255,255,0.12), rgba(255,255,255,0.03) 46%, rgba(255,255,255,0.006) 100%),
    linear-gradient(180deg, rgba(var(--nc-primary-rgb), 0.06), transparent 60%),
    rgba(10, 14, 24, 0.5);
}
.disc-agent-card:hover::before { opacity: 1; }

.disc-list-card {
  position: relative;
  background:
    linear-gradient(168deg, rgba(255,255,255,0.07), rgba(255,255,255,0.02) 50%, rgba(255,255,255,0.004) 100%),
    rgba(10, 14, 24, 0.42);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.22);
  border-radius: 14px;
  padding: 14px 16px;
  backdrop-filter: blur(16px) saturate(1.12);
  -webkit-backdrop-filter: blur(16px) saturate(1.12);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.07), 0 16px 38px -24px rgba(0,0,0,0.92);
  transition: border-color 0.22s ease, box-shadow 0.22s ease, transform 0.22s ease;
  overflow: hidden;
}
.disc-list-card:hover {
  border-color: rgba(var(--nc-primary-rgb),0.50);
  box-shadow: 0 6px 22px -6px rgba(var(--nc-primary-rgb),0.18);
  transform: translateX(2px);
}

@media (prefers-reduced-motion: reduce) {
  .disc-agent-card,
  .disc-list-card { transition: border-color 0.22s ease, box-shadow 0.22s ease; }
  .disc-agent-card:hover,
  .disc-list-card:hover { transform: none !important; }
}

/* ── Featured cards ───────────────────────────────────────── */
.disc-featured-card {
  background: linear-gradient(135deg, rgba(111,66,193,0.08), rgba(214,40,40,0.05));
  border: 1px solid rgba(111,66,193,0.2);
  border-radius: 10px;
  padding: 16px;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.disc-featured-card:hover {
  border-color: rgba(111,66,193,0.4);
  box-shadow: 0 4px 20px rgba(111,66,193,0.12);
}

/* ── Source badges ────────────────────────────────────────── */
.disc-fed-badge {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.05em;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(var(--nc-primary-rgb),0.08);
  border: 1px solid rgba(var(--nc-primary-rgb),0.25);
  color: rgba(var(--nc-primary-rgb),0.8);
  flex-shrink: 0;
}
.disc-local-badge {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.05em;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(0,230,118,0.06);
  border: 1px solid rgba(0,230,118,0.2);
  color: rgba(0,230,118,0.7);
  flex-shrink: 0;
}

/* ── B8 FX-aware discovery badges ─────────────────────────── */
/* Cross-currency, payable via FX on this frame (amber ⇄). */
.disc-fx-badge {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.04em;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(245,158,11,0.10);
  border: 1px solid rgba(245,158,11,0.35);
  color: rgba(245,158,11,0.95);
  white-space: nowrap;
  flex-shrink: 0;
}
/* Cross-currency, NOT transactable — host FX off (muted/locked). */
.disc-fx-locked-badge {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.04em;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(148,163,184,0.10);
  border: 1px solid rgba(148,163,184,0.3);
  color: rgba(148,163,184,0.85);
  white-space: nowrap;
  flex-shrink: 0;
}
/* Greyed card when a cross-currency agent can't be paid from this frame
   (host FX off). Visual de-emphasis + lock cursor; still clickable to inspect. */
.disc-agent-card--fx-locked,
.disc-list-card.disc-agent-card--fx-locked {
  opacity: 0.55;
  filter: grayscale(0.55);
  cursor: not-allowed;
}
.disc-agent-card--fx-locked:hover {
  opacity: 0.8;
  filter: grayscale(0.2);
}

/* ── Status badges ────────────────────────────────────────── */
.disc-badge-active {
  background: rgba(0,230,118,0.1);
  border: 1px solid rgba(0,230,118,0.25);
  color: #00e676;
}
.disc-badge-inactive {
  background: rgba(100,100,100,0.1);
  border: 1px solid rgba(100,100,100,0.2);
  color: #888;
}

/* ── Pricing — hero placement (under agent name) ─────────── */
.disc-price-hero {
  display: inline-flex;
  align-items: baseline;
  gap: 3px;
  font-weight: 800;
  letter-spacing: -0.01em;
  line-height: 1;
}
.disc-price-hero small {
  font-weight: 500;
  opacity: 0.6;
}
.disc-price-hero--paid {
  font-size: 18px;
  color: #f59e0b;
}
.disc-price-hero--paid small { font-size: 11px; }
.disc-price-hero--free {
  font-size: 13px;
  color: rgba(0,230,118,0.5);
  font-weight: 600;
  letter-spacing: 0.04em;
}

/* §V0064 P2 — AGORA equity chip on the Discovery card */
.disc-equity-chip {
  display: inline-flex; align-items: center; gap: 5px; cursor: pointer;
  font-family: 'IBM Plex Mono', monospace; font-size: 11px; font-weight: 700; line-height: 1;
  color: #10b981; background: rgba(16,185,129,0.08);
  border: 1px solid rgba(16,185,129,0.4); border-radius: 99px; padding: 3px 9px;
  transition: background 0.15s, box-shadow 0.15s;
}
.disc-equity-chip:hover { background: rgba(16,185,129,0.18); box-shadow: 0 0 11px rgba(16,185,129,0.3); }
.disc-equity-chip :deep(svg) { width: 12px; height: 12px; }
.disc-equity-sym { font-weight: 800; }
.disc-equity-px { color: rgba(226,232,240,0.7); font-weight: 600; }

/* ── Mini skill chips on Discovery card (§pass18) ───────────────────────── */
.disc-card-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 10px;
}
.disc-card-chip {
  display: inline-block;
  padding: 1px 7px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: rgba(var(--nc-primary-rgb), 0.85);
  background: rgba(var(--nc-primary-rgb), 0.08);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.25);
  border-radius: 99px;
  transition: background 0.16s ease, border-color 0.16s ease;
}
.disc-card-chip--more {
  color: rgba(180, 180, 200, 0.65);
  background: rgba(255, 255, 255, 0.03);
  border-color: rgba(255, 255, 255, 0.08);
}
.disc-agent-card:hover .disc-card-chip:not(.disc-card-chip--more) {
  background: rgba(var(--nc-primary-rgb), 0.14);
  border-color: rgba(var(--nc-primary-rgb), 0.45);
}

/* ── Paid agent card accent (§pass18 — amber left rail + glow on hover) ──── */
.disc-agent-card--paid {
  border-left: 3px solid rgba(245, 158, 11, 0.55);
}
.disc-agent-card--paid::before {
  background: linear-gradient(90deg, rgba(245, 158, 11, 0.20) 0%, rgba(245, 158, 11, 0.85) 50%, rgba(245, 158, 11, 0.20) 100%);
}
.disc-agent-card--paid:hover {
  border-left-color: rgba(245, 158, 11, 0.95);
  box-shadow: 0 10px 32px -8px rgba(245, 158, 11, 0.20), 0 0 0 1px rgba(245, 158, 11, 0.18) inset;
  background: linear-gradient(180deg, rgba(245, 158, 11, 0.04), transparent);
}

/* ── Featured card pricing ───────────────────────────────── */
.disc-featured-card .disc-price-hero--paid {
  font-size: 16px;
}
.disc-featured-card .disc-price-hero--paid small {
  font-size: 10px;
}

/* ── Misc overrides ───────────────────────────────────────── */
.nc-icon-spin { animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

.line-clamp-2 { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.line-clamp-3 { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }

.nc-discovery-page select,
.nc-discovery-page option {
  background-color: var(--nc-dark, #0e1220) !important;
  color: var(--nc-text-primary) !important;
}

/* §pass62.1 (2026-05-21) — Multi-select peer filter (replaces dropdown). */
.disc-frame-filter { /* container hook */ }
.disc-ff-mini-btn {
  background: transparent;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.25);
  color: rgba(var(--nc-primary-rgb), 0.8);
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.6rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  cursor: pointer;
  transition: all 140ms;
}
.disc-ff-mini-btn:hover {
  background: rgba(var(--nc-primary-rgb), 0.08);
  border-color: rgba(var(--nc-primary-rgb), 0.6);
}
.disc-ff-hint {
  font-size: 0.62rem;
  color: rgba(255, 255, 255, 0.42);
  margin-bottom: 0.35rem;
  font-style: italic;
  line-height: 1.3;
}
.disc-ff-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
  max-height: 260px;
  overflow-y: auto;
  scrollbar-width: thin;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  border-radius: 6px;
  padding: 2px;
  background: rgba(0, 0, 0, 0.18);
}
.disc-ff-list::-webkit-scrollbar { width: 6px; }
.disc-ff-list::-webkit-scrollbar-thumb { background: rgba(var(--nc-primary-rgb), 0.25); border-radius: 3px; }
.disc-ff-row {
  display: grid;
  /* five tracks: the index's "+N" (disc-ff-idx) sits after the count on the row; with four, auto-placement put it on a
     second line in the 16 px check column, past its box (the camera, 2026-10-13: "+5096" 18 px past it) */
  grid-template-columns: 16px 18px 1fr auto auto;
  align-items: center;
  gap: 0.4rem;
  padding: 0.32rem 0.45rem;
  border-radius: 4px;
  cursor: pointer;
  transition: background-color 130ms, color 130ms;
  font-size: 0.73rem;
  color: rgba(255, 255, 255, 0.78);
  outline: none;
}
.disc-ff-row:hover { background: rgba(var(--nc-primary-rgb), 0.06); color: #fff; }
.disc-ff-row:focus-visible { box-shadow: 0 0 0 1px rgba(var(--nc-primary-rgb), 0.6); }
.disc-ff-row--active {
  background: rgba(var(--nc-primary-rgb), 0.12);
  color: #fff;
}
.disc-ff-row--active .disc-ff-label { color: rgba(var(--nc-primary-rgb), 0.95); font-weight: 500; }
.disc-ff-row--local { border-left: 2px solid rgba(110, 231, 167, 0.5); padding-left: calc(0.45rem - 2px); }

.disc-ff-check {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  border: 1px solid rgba(255, 255, 255, 0.25);
  border-radius: 3px;
  font-size: 0.66rem;
  color: rgba(var(--nc-primary-rgb), 0.95);
  background: transparent;
  transition: all 130ms;
}
.disc-ff-check--on {
  background: rgba(var(--nc-primary-rgb), 0.16);
  border-color: rgba(var(--nc-primary-rgb), 0.7);
}
.disc-ff-orb {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
}
.disc-ff-orb-fallback {
  display: block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.35);
}
.disc-ff-label {
  font-family: 'JetBrains Mono', monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}
.disc-ff-count {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.62rem;
  color: rgba(var(--nc-primary-rgb), 0.7);
  background: rgba(var(--nc-primary-rgb), 0.06);
  padding: 1px 5px;
  border-radius: 8px;
  min-width: 18px;
  text-align: center;
}
.disc-ff-count--zero {
  color: rgba(255, 255, 255, 0.3);
  background: transparent;
}

/* ═══════════════════════════════════════════════════════════════════════════
   DISCOVERY — 5-PASS POLISH (2026-06-03)
   P1 skeletons · P2 hero/stats · P3 cards · P4 sections · P5 motion + a11y
   ═══════════════════════════════════════════════════════════════════════════ */

/* ── P1 — Skeleton shimmer (perceived perf while the grid loads) ─────────── */
.disc-skel-card {
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px;
  padding: 14px;
  background: rgba(255,255,255,0.015);
}
.disc-skel-row { display: flex; align-items: center; gap: 10px; }
.disc-skel-avatar { width: 38px; height: 38px; border-radius: 10px; flex-shrink: 0; }
.disc-skel-line { height: 11px; border-radius: 5px; }
.disc-skel-chips { display: flex; gap: 6px; margin-top: 14px; }
.disc-skel-chip { width: 46px; height: 14px; border-radius: 99px; }
.disc-shimmer {
  background: linear-gradient(100deg, rgba(255,255,255,0.04) 30%, rgba(var(--nc-primary-rgb,0,210,210),0.13) 50%, rgba(255,255,255,0.04) 70%);
  background-size: 220% 100%;
  animation: disc-shimmer 1.25s ease-in-out infinite;
}
@keyframes disc-shimmer { 0% { background-position: 180% 0; } 100% { background-position: -80% 0; } }

/* ── P2 — Hero title + search bar + stats glow-up ───────────────────────── */
.disc-hero-title {
  background: linear-gradient(92deg, rgba(var(--nc-primary-rgb,0,210,210),1) 0%, #a78bfa 60%, #f0abfc 100%);
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent;
  letter-spacing: -0.01em;
}
.nc-discovery-page input[type="text"]:focus {
  box-shadow: 0 0 0 3px rgba(var(--nc-primary-rgb,0,210,210), 0.14);
  outline: none;
}
/* stat cards: subtle lift + top accent on hover (NeuralCard variant=flat); keyed on .disc-stats since the grid is
   two columns on a phone (md:grid-cols-4), where .grid.grid-cols-4 no longer matched */
.nc-discovery-page .disc-stats > * {
  position: relative;
  transition: transform 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease;
  overflow: hidden;
}
.nc-discovery-page .disc-stats > *:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 22px -12px rgba(var(--nc-primary-rgb,0,210,210), 0.5);
}
.nc-discovery-page .disc-stats > *::after {
  content: ""; position: absolute; left: 0; right: 0; top: 0; height: 2px;
  background: linear-gradient(90deg, transparent, rgba(var(--nc-primary-rgb,0,210,210),0.7), transparent);
  opacity: 0; transition: opacity 0.18s ease;
}
.nc-discovery-page .disc-stats > *:hover::after { opacity: 1; }

/* the page's own frame in the console's layout, which gives a view none (the public /explore shell, .pub-main, gives
   its own 18px 20px): the title sat on the sidebar's edge and the cards ran to the window's edge, the last
   column's trust badge cut off (the camera, 2026-10-13) */
:not(.pub-main) > .nc-discovery-page:not(.disc-embedded) { padding: 2rem; }
@media (max-width: 640px) {
  :not(.pub-main) > .nc-discovery-page:not(.disc-embedded) { padding: 1rem; }
}

/* ── P4 — Section headers (accent bar + count chip) ─────────────────────── */
.disc-section-h { display: flex; align-items: center; gap: 10px; }
.disc-section-accent {
  width: 4px; height: 18px; border-radius: 99px; display: inline-block; flex-shrink: 0;
}
.disc-section-accent--gold { background: linear-gradient(180deg, #fde68a, #f59e0b); box-shadow: 0 0 10px rgba(245,158,11,0.55); }
.disc-section-accent--fx   { background: linear-gradient(180deg, #67e8f9, #06b6d4); box-shadow: 0 0 10px rgba(6,182,212,0.55); }
.disc-section-count {
  font-size: 0.7rem; font-weight: 700; line-height: 1;
  padding: 3px 9px; border-radius: 99px;
  color: rgba(var(--nc-primary-rgb,0,210,210),0.95);
  background: rgba(var(--nc-primary-rgb,0,210,210),0.10);
  border: 1px solid rgba(var(--nc-primary-rgb,0,210,210),0.28);
}

/* ── P3 — Card polish ───────────────────────────────────────────────────── */
/* online status dot gently pulses */
.disc-badge-active .w-1\.5.h-1\.5,
.disc-agent-card .bg-green-400 { animation: disc-dot-pulse 2.4s ease-in-out infinite; }
@keyframes disc-dot-pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(0,230,118,0.5);} 50% { box-shadow: 0 0 0 3px rgba(0,230,118,0);} }
/* Distinguished cards wear a faint prestige ring */
.disc-featured-card {
  position: relative;
  transition: transform 0.16s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}
.disc-featured-card::after {
  content: ""; position: absolute; inset: 0; border-radius: inherit; pointer-events: none;
  box-shadow: inset 0 0 0 1px rgba(245,158,11,0.16);
  opacity: 0; transition: opacity 0.2s ease;
}
.disc-featured-card:hover { transform: translateY(-3px); }
.disc-featured-card:hover::after { opacity: 1; }

/* ── P5 — Motion (staggered entrance) + reduced-motion + a11y focus ─────── */
.disc-card-enter {
  animation: disc-card-in 0.34s cubic-bezier(.22,.61,.36,1) both;
  animation-delay: calc(var(--enter-i, 0) * 28ms);
}
@keyframes disc-card-in { from { opacity: 0; transform: translateY(10px) scale(0.985); } to { opacity: 1; transform: none; } }
.disc-agent-card:focus-visible,
.disc-featured-card:focus-visible {
  outline: none;
  box-shadow: 0 0 0 2px rgba(var(--nc-primary-rgb,0,210,210),0.9), 0 0 0 5px rgba(var(--nc-primary-rgb,0,210,210),0.25);
}
@media (prefers-reduced-motion: reduce) {
  .disc-card-enter { animation: none; }
  .disc-shimmer { animation: none; }
  .disc-badge-active .w-1\.5.h-1\.5, .disc-agent-card .bg-green-400 { animation: none; }
  .disc-featured-card:hover, .disc-agent-card:hover,
  .nc-discovery-page .disc-stats > *:hover { transform: none; }
}

/* B10 — clickable federation-strip nodes (open the registry-card modal) */
.disc-net-node--clickable { cursor: pointer; transition: background 0.15s ease, border-color 0.15s ease, transform 0.15s ease; }
.disc-net-node--clickable:hover { transform: translateY(-1px); border-color: rgba(var(--nc-primary-rgb,0,210,210),0.6); background: rgba(var(--nc-primary-rgb,0,210,210),0.06); }
.disc-net-node--clickable:focus-visible { outline: none; box-shadow: 0 0 0 2px rgba(var(--nc-primary-rgb,0,210,210),0.8); }

/* ═══ §v0003 polish (2 passes) — premium accents + a11y ═══ */
/* pass 1: agent-card top accent always faintly lit (was hover-only) + stronger lift */
.disc-agent-card::before { opacity: 0.45; }
.disc-agent-card:hover::before { opacity: 1; }
.disc-agent-card:hover { transform: translateY(-3px); }
/* pass 2: visible focus ring for keyboard nav */
.nc-discovery-page :is(button, input, select, [tabindex]):focus-visible {
  outline: 2px solid rgba(var(--nc-primary-rgb), 0.55); outline-offset: 2px; border-radius: 8px;
}

/* §AGENTDISC #188 — proven-work band + receipts drawer (scoped styles follow
   teleported nodes: Vue stamps the scope id on Teleport content too). */
.disc-tr-band { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; cursor: pointer; }
.disc-tr-chip {
  font-size: 0.68rem; padding: 1px 7px; border-radius: 999px; white-space: nowrap;
  border: 1px solid rgba(148, 163, 184, 0.25); color: #94a3b8; background: rgba(148, 163, 184, 0.06);
}
.disc-tr-chip--jobs { border-color: rgba(34, 211, 238, 0.4); color: #22d3ee; background: rgba(34, 211, 238, 0.07); }
.disc-tr-chip--stars { border-color: rgba(245, 158, 11, 0.4); color: #f59e0b; background: rgba(245, 158, 11, 0.07); }
.disc-tr-chip--xreg { border-color: rgba(168, 85, 247, 0.4); color: #c084fc; background: rgba(168, 85, 247, 0.07); }
.disc-tr-chip--disputes { border-color: rgba(244, 63, 94, 0.4); color: #fb7185; background: rgba(244, 63, 94, 0.07); }
.disc-tr-band:hover .disc-tr-chip--jobs { background: rgba(34, 211, 238, 0.16); }
.disc-tr-more { font-size: 0.66rem; color: #22d3ee; opacity: 0.75; }
.disc-tr-overlay {
  position: fixed; inset: 0; z-index: 90; background: rgba(2, 6, 23, 0.72);
  backdrop-filter: blur(3px); display: flex; align-items: center; justify-content: center; padding: 20px;
}
.disc-tr-modal {
  width: min(680px, 94vw); max-height: 84vh; overflow-y: auto;
  background: #0b1220; border: 1px solid rgba(34, 211, 238, 0.25); border-radius: 14px;
  padding: 18px 20px; box-shadow: 0 18px 60px rgba(0, 0, 0, 0.5);
}
.disc-tr-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; margin-bottom: 12px; }
.disc-tr-title { font-size: 1.05rem; font-weight: 700; color: #e2e8f0; }
.disc-tr-sub { font-size: 0.72rem; color: #94a3b8; margin-top: 2px; }
.disc-tr-close { color: #94a3b8; font-size: 0.9rem; padding: 4px 8px; border-radius: 8px; }
.disc-tr-close:hover { color: #fff; background: rgba(148, 163, 184, 0.12); }

/* §AGENTDISC #191 — why-ranked-here chip + breakdown */
.disc-why-chip {
  font-size: 0.62rem; padding: 0 6px; border-radius: 999px; cursor: pointer;
  border: 1px solid rgba(148, 163, 184, 0.3); color: #94a3b8; background: transparent;
}
.disc-why-chip:hover { color: #22d3ee; border-color: rgba(34, 211, 238, 0.4); }
.disc-why-pop {
  margin-top: 8px; padding: 8px 10px; border-radius: 8px; font-size: 0.68rem;
  border: 1px solid rgba(148, 163, 184, 0.2); background: rgba(15, 23, 42, 0.55);
}
.disc-why-row { display: flex; gap: 8px; align-items: baseline; padding: 1px 0; }
.disc-why-label { color: #94a3b8; }
.disc-why-value { color: #e2e8f0; margin-left: auto; }
.disc-why-pts { width: 52px; text-align: right; font-family: ui-monospace, monospace; }
.trp-okc { color: #4ade80; }
.trp-latec { color: #fb7185; }
.disc-why-note { color: #94a3b8; font-style: italic; padding: 2px 0; }
.disc-why-total {
  margin-top: 4px; padding-top: 4px; border-top: 1px dashed rgba(148, 163, 184, 0.2);
  color: #22d3ee; display: flex; justify-content: space-between; gap: 8px;
}
.disc-why-formula { color: #64748b; cursor: help; text-decoration: underline dotted; }

/* §REPBOND — the bond filter (the chip's own styles live in BondChip.vue) */
.disc-bond-filter { display: inline-flex; align-items: center; gap: 0.4rem; font-size: 0.75rem; margin-bottom: 0.5rem; cursor: pointer; }
.disc-bond-filter input { accent-color: rgb(var(--nc-primary-rgb)); }
.disc-unbonded-refused { margin: 0.15rem 0 0.4rem 1.1rem; font-size: 0.7rem; line-height: 1.35; color: var(--nc-warning, #f0b429); }

/* §FESUITE: the card's name is its button (keyboard, screen reader); it keeps the heading's look */
.disc-card-open {
  all: unset;
  cursor: pointer;
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.disc-card-open:focus-visible { outline: 2px solid var(--nc-primary, #00e5ff); outline-offset: 2px; border-radius: 2px; }
/* §COCKPITDESK (2026-10-15), the phone camera's small-target readings (WCAG 2.5.8, 24 x 24 CSS px): a finger's target grows, the glyph keeps its size */
@media (pointer: coarse), (max-width: 640px) {
  .disc-info-btn { width: 24px; height: 24px; line-height: 22px; font-size: 11px; }
}
/* §COCKPITDESK (2026-10-15), the phone camera on /explore: in a two-column tile the label, its scope badge and the figure
   shared one row and the figure ran past the tile ("Active (24h) LOCAL 16|8"). On a phone the row wraps. */
@media (max-width: 640px) {
  .disc-stat-row { flex-wrap: wrap; row-gap: 2px; column-gap: 8px; }
}
</style>
