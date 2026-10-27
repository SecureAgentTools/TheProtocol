<template>
  <div class="contracts-root">

    <!-- Ambient background layer (matches AdminCanaries / AdminReactors) -->
    <div class="cc-ambient" aria-hidden="true">
      <div class="cc-grid"></div>
      <div class="cc-scan"></div>
      <div class="cc-glow cc-glow-1"></div>
      <div class="cc-glow cc-glow-2"></div>
    </div>

    <!-- Hero strip — mirrors canary hero pattern -->
    <section class="cc-hero">
      <div class="cc-hero-inner">
        <div class="cc-chip-hero"><span class="cc-chip-dot"></span>{{ t('contractsView.hero.chip') }}</div>
        <h1 class="cc-h1">
          {{ t('contractsView.hero.h1a') }}<span class="cc-accent">{{ t('contractsView.hero.h1Accent') }}</span>{{ t('contractsView.hero.h1b') }}
        </h1>
        <p class="cc-lead">
          {{ t('contractsView.hero.lead') }}
        </p>
        <button class="ctr-ex-toggle" @click="showExplainer = !showExplainer" :aria-expanded="showExplainer">
          <span class="ctr-ex-caret" :class="{ open: showExplainer }">›</span>
          {{ showExplainer ? t('contractsView.explainer.hide') : t('contractsView.explainer.toggle') }}
        </button>
      </div>
    </section>

    <!-- ── How contracts work ───────────────────────────────────────────
         The view used to explain nothing: a newcomer could not tell when money
         moves, what a milestone is, or where a rejection goes. Collapsed by
         default so it costs regulars nothing. -->
    <section v-if="showExplainer" class="ctr-ex">
      <h2 class="ctr-ex__h">{{ t('contractsView.explainer.title') }}</h2>
      <ol class="ctr-ex__steps">
        <li v-for="s in explainerSteps" :key="s.n" class="ctr-ex__step">
          <span class="ctr-ex__num">{{ s.n }}</span>
          <div>
            <div class="ctr-ex__st">{{ s.title }}</div>
            <p class="ctr-ex__sd">{{ s.desc }}</p>
          </div>
        </li>
      </ol>
      <div class="ctr-ex__notes">
        <p v-for="(nt, i) in explainerNotes" :key="i" class="ctr-ex__note">
          <span class="ctr-ex__dot"></span>{{ nt }}
        </p>
      </div>
    </section>

    <!-- ── Command Bar ──────────────────────────────────────────────── -->
    <div class="cmd-bar">
      <div class="cmd-bar__left">
        <div class="cmd-bar__icon">⬡</div>
        <div>
          <h2 class="cmd-bar__title" data-tour="ctr-hero">{{ t('contractsView.cmdBar.title') }}</h2>
          <p class="cmd-bar__sub">{{ t('contractsView.cmdBar.sub', { count: listCount }) }}</p>
        </div>
      </div>
      <div class="cmd-bar__right">
        <button class="cmd-btn cmd-btn--ghost" @click="reload" :disabled="contractStore.loading">
          <span v-if="contractStore.loading" class="mini-spin" />
          <span v-else>↻</span>
          {{ t('contractsView.cmdBar.refresh') }}
        </button>
        <button
          class="cmd-btn cmd-btn--primary"
          data-tour="ctr-new"
          @click="showCreate = true"
          :disabled="!activeAgentDid"
          :title="activeAgentDid ? t('contractsView.cmdBar.proposeReady') : t('contractsView.cmdBar.proposeNoAgent')"
        >
          {{ t('contractsView.cmdBar.propose') }}
        </button>
      </div>
    </div>

    <!-- ── No agent warning ────────────────────────────────────────── -->
    <div v-if="!activeAgentDid" class="no-agent-banner">
      <svg class="cc-inline-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.6 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.6a2 2 0 0 0-3.4 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
      {{ t('contractsView.noAgent') }}
    </div>

    <!-- ── Tab Bar ─────────────────────────────────────────────────── -->
    <div class="tab-bar" data-tour="ctr-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        class="tab-btn"
        :data-tour="'contracts-tab-' + tab.id"
        :class="{ active: activeTab === tab.id }"
        @click="activeTab = tab.id"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- ═══════════════════════════════════════════════════════════════
         TAB: CONTRACTS
    ═════════════════════════════════════════════════════════════════ -->
    <div v-show="activeTab === 'contracts'">

      <!-- Stat cards -->
      <div class="stat-grid">
        <div
          v-for="card in statCards"
          :key="card.status"
          class="stat-card"
          data-tour="ctr-stats"
          :class="{ active: contractStore.statusFilter === card.status }"
          :style="{ '--accent': card.color }"
          @click="contractStore.setStatusFilter(card.status)"
        >
          <div class="stat-card__dot" :style="{ background: card.color }" />
          <div class="stat-card__count">{{ countsKnown ? card.count : '—' }}</div>
          <div class="stat-card__label">{{ card.label }}</div>
          <div v-if="card.value" class="stat-card__value">{{ card.value }}</div>
        </div>
      </div>

      <!-- §XHIREFE — offers mirrored from OTHER registries for the acting
           agent (read-only couriers from /contracts/v2/mine, replica:true).
           Renders only when replicas exist: this is a section among many, the
           §DISCREFINE auto-hide-allowed case. Same door component as the
           bridge WORK modal — ONE brain, two mounts, no drift. -->
      <!-- §TWOAGENT V0442: the rail's HOME rows too. On a frame where D8 retired the legacy list (EU, ASIA) this strip is
           the only place a v2 contract appears, and it used to keep only the replicas: a contract's client never saw it
           at its own home. Home rows are read-only here (their escrow and every state change are on this registry). -->
      <div v-if="replicaRows.length || homeRows.length" class="ctr-replica-strip" data-testid="ctr-replica-strip">
        <template v-if="homeRows.length">
          <div class="ctr-replica-head" data-testid="ctr-home-head">
            <Icon name="mdi:home" />
            <span>{{ t('contractsView.railHereHead', 'Contracts on this registry for your acting agent') }}</span>
          </div>
          <div v-for="r in homeRows" :key="r.id" class="ctr-replica-row" data-testid="ctr-home-row">
            <button type="button" class="ctr-replica-btn" :data-testid="`ctr-home-open-${r.id}`"
                    @click="homeOpen = homeOpen === r.id ? null : r.id">
              <span class="ctr-replica-chip ctr-home-chip"><Icon name="mdi:home" /> {{ t('contractsView.railHereChip', 'here') }}</span>
              <span class="ctr-replica-title">{{ r.title || r.id }}</span>
              <span v-if="railRoleText(r)" class="ctr-home-role">{{ railRoleText(r) }}</span>
              <span v-if="r.counterparty_home_registry" class="ctr-home-with">{{ tp('contractsView.railWith', 'with {home}', { home: r.counterparty_home_registry }) }}</span>
              <span class="ctr-replica-amt">{{ fmt(r.total_amount, 4) }} {{ r.currency }}</span>
              <span class="ctr-replica-st">{{ r.status }}</span>
            </button>
            <p v-if="homeOpen === r.id" class="ctr-home-note" data-testid="ctr-home-note">{{ t('contractsView.railHereNote',
              'This contract lives on this registry: its escrow and every state change happen here. A delivered milestone is released or rejected through the contract API (releaseContractMilestone, rejectContractMilestone); this page does not offer those yet.') }}</p>
          </div>
        </template>
        <div v-if="replicaRows.length" class="ctr-replica-head">
          <Icon name="mdi:earth" />
          <span>{{ t('contractsView.replicaStripAll', 'Cross-registry contracts for your acting agent') }}</span>
        </div>
        <div v-for="r in replicaRows" :key="r.id" class="ctr-replica-row" data-testid="ctr-replica-row">
          <button type="button" class="ctr-replica-btn" :data-testid="`ctr-replica-open-${r.id}`"
                  @click="replicaOpen = replicaOpen === r.id ? null : r.id">
            <span class="ctr-replica-chip"><Icon name="mdi:earth" /> {{ r.home_registry }}</span>
            <span class="ctr-replica-title">{{ r.title || r.id }}</span>
            <span class="ctr-replica-amt">{{ fmt(r.total_amount, 4) }} {{ r.currency }}</span>
            <span class="ctr-replica-st">{{ r.status }}</span>
          </button>
          <ReplicaContractDoor v-if="replicaOpen === r.id" :contract="r" @acted="loadReplicas" />
        </div>
      </div>

      <!-- Filter bar (it filters the legacy grid; on a frame that retired that list there is nothing for it to filter) -->
      <div v-if="!contractStore.legacyRetired" class="filter-bar">
        <!-- Status pills -->
        <div class="filter-pills">
          <button
            v-for="pill in statusPills"
            :key="pill.val"
            class="pill"
            :class="{ active: contractStore.statusFilter === pill.val }"
            @click="contractStore.setStatusFilter(pill.val)"
          >{{ pill.label }}</button>
        </div>

        <!-- Role filter -->
        <div class="filter-group">
          <label class="filter-label">{{ t('contractsView.filters.role') }}</label>
          <select v-model="roleFilter" class="filter-select" :aria-label="t('contractsView.filters.role')" @change="contractStore.setRoleFilter(roleFilter)">
            <option value="all">{{ t('contractsView.filters.roleAll') }}</option>
            <option value="client">{{ t('contractsView.filters.roleClient') }}</option>
            <option value="upgrader">{{ t('contractsView.filters.roleUpgrader') }}</option>
          </select>
        </div>

        <!-- Search -->
        <div class="filter-group filter-group--grow">
          <input
            v-model="searchQuery"
            class="filter-input"
            :placeholder="t('contractsView.filters.searchPlaceholder')"
            @input="contractStore.setSearch(searchQuery)"
          />
        </div>

        <!-- Clear -->
        <button
          v-if="hasActiveFilters"
          class="filter-clear"
          @click="clearFilters"
        >{{ t('contractsView.filters.clear') }}</button>
      </div>

      <!-- §FESUITE (V0575): a read that failed is not "no contracts" -->
      <ReadFailedNotice v-if="!contractStore.loading && contractStore.legacyRetired && railFailed" :retry="loadReplicas"
                        data-testid="ctr-rail-failed" />
      <ReadFailedNotice v-else-if="!contractStore.loading && !contractStore.legacyRetired && contractStore.error && !contractStore.contracts.length"
                        :retry="reload" data-testid="ctr-list-failed" />
      <!-- Empty state -->
      <div v-else-if="!contractStore.loading && contractStore.legacyRetired && !replicaRows.length && !homeRows.length"
           class="empty-state" data-testid="ctr-rail-empty">
        <div class="empty-state__icon">⬡</div>
        <p class="empty-state__msg">{{ t('contractsView.empty.railNone', 'Your acting agent has no contracts on the contract rail yet.') }}</p>
      </div>
      <div v-else-if="!contractStore.loading && !contractStore.legacyRetired && contractStore.filteredContracts.length === 0" class="empty-state">
        <div class="empty-state__icon">⬡</div>
        <!-- §COCKPITDESK (2026-10-15): with no filter set, "match your filters" + Clear filters blamed filters for an empty list -->
        <template v-if="hasActiveFilters">
          <p class="empty-state__msg">{{ t('contractsView.empty.noMatch') }}</p>
          <button class="cmd-btn cmd-btn--ghost" @click="clearFilters">{{ t('contractsView.empty.clearBtn') }}</button>
        </template>
        <p v-else class="empty-state__msg" data-testid="ctr-empty-none">{{ t('contractsView.empty.none', 'No contracts yet. Propose one to an agent, or accept an open proposal when one appears here.') }}</p>
      </div>

      <!-- Loading -->
      <div v-else-if="contractStore.loading && contractStore.contracts.length === 0" class="empty-state">
        <div class="mini-spin" style="width:32px; height:32px; border-width:3px;" />
        <p class="empty-state__msg">{{ t('contractsView.empty.loading') }}</p>
      </div>

      <!-- Contract grid -->
      <div v-else class="contract-grid">
        <div
          v-for="c in contractStore.filteredContracts"
          :key="contractStore.ctrRef(c)"
          class="contract-card"
          :class="[`status-${c.status.toLowerCase().replace('_','-')}`]"
          @click="openDrawer(contractStore.ctrRef(c))"
        >
          <!-- Card header -->
          <div class="cc-header">
            <div class="cc-meta">
              <span class="cc-status-dot" :style="{ background: statusColor(c.status) }" />
              <!-- §FESUITE: the card opens on a click only; the id is the keyboard door to the same drawer -->
              <button type="button" class="cc-id cc-id-btn" :data-testid="'ctr-open-' + contractStore.ctrRef(c)"
                      :aria-label="tp('contractsView.card.openAria', 'Open contract {id}', { id: contractStore.ctrLabel(c) })"
                      @click.stop="openDrawer(contractStore.ctrRef(c))">{{ contractStore.ctrLabel(c) }}</button>
              <span class="cc-status-badge" :style="{ color: statusColor(c.status), borderColor: statusColor(c.status) + '40' }">
                {{ statusLabel(c.status) }}
              </span>
            </div>
            <div class="cc-role-chip" :class="roleChipClass(c)">{{ roleLabel(c) }}</div>
          </div>

          <!-- Scope -->
          <p class="cc-scope">{{ c.scope_description.slice(0, 96) }}{{ c.scope_description.length > 96 ? '…' : '' }}</p>

          <!-- Repo -->
          <p class="cc-repo" @click.stop>
            <a :href="safeExternalUrl(c.source_code_repo_url)" target="_blank" rel="noopener noreferrer" @click.stop>
              {{ shortRepo(c.source_code_repo_url) }}
            </a>
            <span v-if="c.source_code_branch !== 'main'" class="cc-branch">{{ c.source_code_branch }}</span>
          </p>

          <!-- Pipeline bar -->
          <div class="cc-pipeline">
            <div
              v-for="(stage, idx) in pipeline"
              :key="stage.status"
              class="cc-pipeline-stage"
              :class="{ done: pipelineIdx(c.status) >= idx, current: pipelineIdx(c.status) === idx }"
            >
              <div class="cc-pip-dot" />
              <span class="cc-pip-label">{{ stage.short }}</span>
              <div v-if="idx < pipeline.length - 1" class="cc-pip-line" />
            </div>
          </div>

          <!-- Footer -->
          <div class="cc-footer">
            <div class="cc-payment">
              <span class="cc-avt">{{ c.payment_amount.toLocaleString(appLocale()) }}</span>
              <span class="cc-avt-unit">{{ localCurrency }}</span>
            </div>
            <div class="cc-actions" @click.stop>
              <!-- Accept (PROPOSED + not my contract as client) -->
              <button
                v-if="canAccept(c)"
                class="cc-btn cc-btn--cyan"
                @click.stop="openAccept(c)"
              >{{ t('contractsView.card.accept') }}</button>
              <!-- Submit work (ACCEPTED + I'm upgrader) -->
              <button
                v-if="canSubmit(c)"
                class="cc-btn cc-btn--amber"
                @click.stop="openSubmit(c)"
              >{{ t('contractsView.card.submit') }}</button>
              <!-- Approve (PENDING_MERGE + I'm client) -->
              <button
                v-if="canApprove(c)"
                class="cc-btn cc-btn--green"
                @click.stop="openApprove(c)"
              >{{ t('contractsView.card.approve') }}</button>
              <!-- Malpractice (ACCEPTED or PENDING_MERGE + I'm a party) -->
              <button
                v-if="canMalpractice(c)"
                class="cc-btn cc-btn--red"
                :aria-label="t('contractsView.drawer.footer.fileMalpractice')"
                :title="t('contractsView.drawer.footer.fileMalpractice')"
                @click.stop="openMalpractice(c)"
              ><span aria-hidden="true">⚑</span></button>
            </div>
          </div>
        </div>
      </div>

    </div><!-- end contracts tab -->

    <!-- ═══════════════════════════════════════════════════════════════
         TAB: TEMPLATES (CONTRACT SPINE P4 — free + professionally maintained paid)
    ═════════════════════════════════════════════════════════════════ -->
    <div v-show="activeTab === 'templates'">
      <TemplatesTab @minted="reload" />
    </div>

    <!-- ═══════════════════════════════════════════════════════════════
         TAB: ANALYTICS
    ═════════════════════════════════════════════════════════════════ -->
    <div v-show="activeTab === 'analytics'" class="analytics-panel">
      <div class="analytics-grid">

        <!-- Stage distribution -->
        <div class="an-card">
          <h3 class="an-card__title">{{ t('contractsView.analytics.stageDist') }}</h3>
          <div class="an-bars">
            <div v-for="bar in stageBars" :key="bar.label" class="an-bar-row">
              <span class="an-bar-label">{{ bar.label }}</span>
              <div class="an-bar-track">
                <div
                  class="an-bar-fill"
                  :style="{ width: bar.pct + '%', background: bar.color }"
                />
              </div>
              <span class="an-bar-count">{{ bar.count }}</span>
            </div>
          </div>
        </div>

        <!-- Summary stats -->
        <div class="an-card">
          <h3 class="an-card__title">{{ t('contractsView.analytics.summary') }}</h3>
          <div class="an-stats">
            <div class="an-stat">
              <span class="an-stat__label">{{ t('contractsView.analytics.totalContracts') }}</span>
              <span class="an-stat__val">{{ contractStore.stats.total }}</span>
            </div>
            <div class="an-stat">
              <span class="an-stat__label">{{ t('contractsView.analytics.totalValue') }}</span>
              <span class="an-stat__val cyan">{{ contractStore.stats.totalValue.toLocaleString(appLocale()) }} {{ localCurrency }}</span>
            </div>
            <div class="an-stat">
              <span class="an-stat__label">{{ t('contractsView.analytics.completedValue') }}</span>
              <span class="an-stat__val green">{{ contractStore.stats.completedValue.toLocaleString(appLocale()) }} {{ localCurrency }}</span>
            </div>
            <div class="an-stat">
              <span class="an-stat__label">{{ t('contractsView.analytics.successRate') }}</span>
              <span class="an-stat__val" :class="contractStore.stats.successRate >= 70 ? 'green' : 'amber'">
                {{ contractStore.stats.successRate }}%
              </span>
            </div>
            <div class="an-stat">
              <span class="an-stat__label">{{ t('contractsView.analytics.avgPayment') }}</span>
              <span class="an-stat__val">{{ contractStore.stats.avgPayment.toLocaleString(appLocale()) }} {{ localCurrency }}</span>
            </div>
          </div>
        </div>

        <!-- My activity -->
        <div v-if="activeAgentDid" class="an-card">
          <h3 class="an-card__title">{{ t('contractsView.analytics.myActivity') }}</h3>
          <div class="an-bars">
            <div v-for="bar in myActivityBars" :key="bar.label" class="an-bar-row">
              <span class="an-bar-label">{{ bar.label }}</span>
              <div class="an-bar-track">
                <div class="an-bar-fill" :style="{ width: bar.pct + '%', background: bar.color }" />
              </div>
              <span class="an-bar-count">{{ bar.count }}</span>
            </div>
          </div>
        </div>

      </div>
    </div>

    <!-- ── Detail Drawer ───────────────────────────────────────────── -->
    <Transition name="drawer">
      <div v-if="contractStore.drawerOpen && contractStore.activeContract" class="drawer-overlay" @click.self="contractStore.closeDrawer()">
        <div ref="drawerEl" class="drawer" role="dialog" aria-modal="true" aria-labelledby="ctr-drawer-title">
          <div class="drawer-header">
            <div>
              <span id="ctr-drawer-title" class="drawer-title">{{ t('contractsView.drawer.contract') }} {{ contractStore.ctrLabel(contractStore.activeContract) }}</span>
              <span class="drawer-status-badge" :style="{ color: statusColor(contractStore.activeContract.status) }">
                {{ statusLabel(contractStore.activeContract.status) }}
              </span>
            </div>
            <button type="button" class="tp-modal-close" :aria-label="t('common.close', 'Close')" @click="contractStore.closeDrawer()">×</button>
          </div>

          <!-- Drawer tabs -->
          <div class="drawer-tabs">
            <button
              v-for="dt in drawerTabsWithLabels"
              :key="dt.id"
              class="drawer-tab"
              :class="{ active: drawerTab === dt.id }"
              @click="drawerTab = dt.id"
            >{{ dt.label }}</button>
          </div>

          <div class="drawer-body">
            <!-- Overview tab -->
            <div v-if="drawerTab === 'Overview'">
              <div class="tp-row"><span class="tp-row__label">{{ t('contractsView.drawer.rows.id') }}</span><span class="tp-row__value tp-row__value--mono">{{ contractStore.ctrLabel(contractStore.activeContract) }}</span></div>
              <div class="tp-row"><span class="tp-row__label">{{ t('contractsView.drawer.rows.status') }}</span><span class="tp-row__value" :style="{ color: statusColor(contractStore.activeContract.status) }">{{ statusLabel(contractStore.activeContract.status) }}</span></div>
              <div class="tp-row"><span class="tp-row__label">{{ t('contractsView.drawer.rows.client') }}</span><span class="tp-row__value tp-row__value--mono" style="font-size:0.7rem;">{{ contractStore.activeContract.client_agent_did }}</span></div>
              <div class="tp-row"><span class="tp-row__label">{{ t('contractsView.drawer.rows.upgrader') }}</span><span class="tp-row__value tp-row__value--mono" style="font-size:0.7rem;">{{ contractStore.activeContract.upgrader_agent_did || '—' }}</span></div>
              <div class="tp-row"><span class="tp-row__label">{{ t('contractsView.drawer.rows.payment') }}</span><span class="tp-row__value tp-row__value--big">{{ contractStore.activeContract.payment_amount.toLocaleString(appLocale()) }} {{ localCurrency }}</span></div>
              <div v-if="contractStore.activeContract.access_credentials_id && isPartyToActive" class="tp-row">
                <span class="tp-row__label">{{ t('contractsView.drawer.rows.credentials') }}</span>
                <span class="tp-row__value tp-row__value--mono" style="font-size:0.7rem; cursor:pointer;" @click="copyToClipboard(contractStore.activeContract.access_credentials_id!)">
                  {{ contractStore.activeContract.access_credentials_id }}
                  <svg class="cc-inline-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                </span>
              </div>
              <div class="tp-row"><span class="tp-row__label">{{ t('contractsView.drawer.rows.created') }}</span><span class="tp-row__value">{{ fmtDate(contractStore.activeContract.created_at) }}</span></div>
              <div v-if="contractStore.activeContract.accepted_at" class="tp-row"><span class="tp-row__label">{{ t('contractsView.drawer.rows.accepted') }}</span><span class="tp-row__value">{{ fmtDate(contractStore.activeContract.accepted_at) }}</span></div>
              <div v-if="contractStore.activeContract.completed_at" class="tp-row"><span class="tp-row__label">{{ t('contractsView.drawer.rows.completed') }}</span><span class="tp-row__value">{{ fmtDate(contractStore.activeContract.completed_at) }}</span></div>

              <div style="margin-top: 1rem;">
                <p class="tp-label">{{ t('contractsView.drawer.scope') }}</p>
                <p style="color: #c8d6e8; font-size: 0.875rem; line-height: 1.6; background: rgba(255,255,255,0.03); border-radius: 6px; padding: 0.7rem 0.9rem; border: 1px solid rgba(var(--nc-primary-rgb),0.1);">
                  {{ contractStore.activeContract.scope_description }}
                </p>
              </div>
            </div>

            <!-- Repository tab -->
            <div v-if="drawerTab === 'Repository'">
              <div class="tp-row"><span class="tp-row__label">{{ t('contractsView.drawer.repo.repository') }}</span></div>
              <a :href="safeExternalUrl(contractStore.activeContract.source_code_repo_url)" target="_blank" rel="noopener noreferrer" class="drawer-link">
                {{ contractStore.activeContract.source_code_repo_url }}
              </a>
              <div class="tp-row" style="margin-top:0.75rem;"><span class="tp-row__label">{{ t('contractsView.drawer.repo.branch') }}</span><span class="tp-row__value tp-row__value--mono">{{ contractStore.activeContract.source_code_branch }}</span></div>
              <div v-if="contractStore.activeContract.pr_url" style="margin-top:0.75rem;">
                <div class="tp-row"><span class="tp-row__label">{{ t('contractsView.drawer.repo.pullRequest') }}</span></div>
                <a :href="safeExternalUrl(contractStore.activeContract.pr_url)" target="_blank" rel="noopener noreferrer" class="drawer-link">
                  {{ contractStore.activeContract.pr_url }}
                </a>
              </div>
              <div v-else class="drawer-empty">{{ t('contractsView.drawer.repo.noPr') }}</div>
            </div>

            <!-- Criteria tab -->
            <div v-if="drawerTab === 'Criteria'">
              <div v-if="activeCriteriaEntries.length">
                <div v-for="([k, v]) in activeCriteriaEntries" :key="k" class="tp-row">
                  <span class="tp-row__label">{{ k }}</span>
                  <span class="tp-row__value tp-row__value--mono">{{ v }}</span>
                </div>
              </div>
              <div v-else class="drawer-empty">{{ t('contractsView.drawer.criteriaEmpty') }}</div>
            </div>

            <!-- Timeline tab -->
            <div v-if="drawerTab === 'Timeline'">
              <div class="timeline">
                <div class="tl-item">
                  <div class="tl-dot done" />
                  <div class="tl-content">
                    <span class="tl-label">{{ t('contractsView.drawer.timeline.proposed') }}</span>
                    <span class="tl-date">{{ fmtDate(contractStore.activeContract.created_at) }}</span>
                  </div>
                </div>
                <div class="tl-item">
                  <div class="tl-dot" :class="{ done: contractStore.activeContract.accepted_at }" />
                  <div class="tl-content">
                    <span class="tl-label">{{ t('contractsView.drawer.timeline.accepted') }}</span>
                    <span class="tl-date">{{ contractStore.activeContract.accepted_at ? fmtDate(contractStore.activeContract.accepted_at) : t('contractsView.drawer.timeline.pending') }}</span>
                  </div>
                </div>
                <div class="tl-item">
                  <div class="tl-dot" :class="{ done: contractStore.activeContract.pr_url }" />
                  <div class="tl-content">
                    <span class="tl-label">{{ t('contractsView.drawer.timeline.prSubmitted') }}</span>
                    <span class="tl-date">{{ contractStore.activeContract.pr_url ? t('contractsView.drawer.timeline.submitted') : t('contractsView.drawer.timeline.pending') }}</span>
                  </div>
                </div>
                <div class="tl-item">
                  <div class="tl-dot" :class="{ done: contractStore.activeContract.completed_at }" />
                  <div class="tl-content">
                    <span class="tl-label">{{ t('contractsView.drawer.timeline.completed') }}</span>
                    <span class="tl-date">{{ contractStore.activeContract.completed_at ? fmtDate(contractStore.activeContract.completed_at) : t('contractsView.drawer.timeline.pending') }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Drawer actions -->
          <div class="drawer-footer" v-if="contractStore.activeContract">
            <button v-if="canAccept(contractStore.activeContract)" class="cmd-btn cmd-btn--primary" data-tour="ctr-accept" @click="openAccept(contractStore.activeContract!)">{{ t('contractsView.drawer.footer.accept') }}</button>
            <button v-if="canSubmit(contractStore.activeContract)" class="cmd-btn cmd-btn--ghost" @click="openSubmit(contractStore.activeContract!)">{{ t('contractsView.drawer.footer.submit') }}</button>
            <button v-if="canApprove(contractStore.activeContract)" class="cmd-btn cmd-btn--primary" data-tour="ctr-approve" style="background: rgba(34,197,94,0.15); border-color: rgba(34,197,94,0.4); color: rgb(34,197,94);" @click="openApprove(contractStore.activeContract!)">{{ t('contractsView.drawer.footer.approvePay') }}</button>
            <button v-if="canMalpractice(contractStore.activeContract)" class="cmd-btn" style="background: rgba(239,68,68,0.08); border:1px solid rgba(239,68,68,0.3); color: rgb(239,68,68); font-family: 'IBM Plex Mono', monospace; font-size:0.72rem; letter-spacing:0.1em; text-transform:uppercase; padding:0.55rem 1rem; border-radius:6px; cursor:pointer;" @click="openMalpractice(contractStore.activeContract!)">{{ t('contractsView.drawer.footer.fileMalpractice') }}</button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- ── Modals ──────────────────────────────────────────────────── -->
    <CreateContractModal v-if="showCreate" @close="showCreate = false" @created="onCreated" />
    <AcceptContractModal v-if="modalContract && showAccept" :contract="modalContract" @close="showAccept = false" @accepted="onAccepted" />
    <SubmitWorkModal v-if="modalContract && showSubmit" :contract="modalContract" @close="showSubmit = false" @submitted="onSubmitted" />
    <ApproveCompletionModal v-if="modalContract && showApprove" :contract="modalContract" @close="showApprove = false" @completed="onCompleted" />
    <MalpracticeModal v-if="modalContract && showMalpractice" :contract="modalContract" @close="showMalpractice = false" />

  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
// a v2 contract's amount arrives as str(Decimal): "2.0000000000", and "0E-10" for a zero; the strip printed it raw
// (agentvault2-69's EU gallery, V0638: 47 of 50 rows "0E-10 ECU"). fmt reads it as a number, in the app's locale.
import { fmt } from '@/services/cockpit/num'
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useFocusTrap } from '@/composables/useFocusTrap'
import { useRoute as _useRouteAgentdisc } from 'vue-router'
import { safeExternalUrl } from '@/utils/safeUrl'
import { useContractStore } from '@/stores/contracts'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
import { useI18n } from '@/composables/useI18n'
import type { BackendContract } from '@/services/api/contracts'
import CreateContractModal from '@/components/contracts/CreateContractModal.vue'
import AcceptContractModal from '@/components/contracts/AcceptContractModal.vue'
import SubmitWorkModal from '@/components/contracts/SubmitWorkModal.vue'
import ApproveCompletionModal from '@/components/contracts/ApproveCompletionModal.vue'
import MalpracticeModal from '@/components/contracts/MalpracticeModal.vue'
import TemplatesTab from '@/components/contracts/TemplatesTab.vue'  // CONTRACT SPINE P4
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import ReplicaContractDoor from '@/components/contracts/ReplicaContractDoor.vue'  // §XHIREFE
import { splitRailRows, railTileCounts, railRole } from '@/services/contracts/railRows'  // §TWOAGENT V0442
import { contractsV2Api } from '@/services/api/contractsV2'

// ─── i18n ────────────────────────────────────────────────────────────────────
const { t, tp } = useI18n()
import { useCurrency } from '@/composables/useCurrency'
const { localCurrency } = useCurrency()

// ─── Stores ──────────────────────────────────────────────────────────────────
const contractStore = useContractStore()
const authStore = useAuthStore()
const uiStore = useUIStore()

const activeAgentDid = computed(
  () => authStore.activeAgent?.did || authStore.activeAgent?.agent_did || ''
)

// ─── Tabs ────────────────────────────────────────────────────────────────────
// ── "How contracts work" explainer ────────────────────────────────────────
// Collapsed by default; the toggle lives in the hero. Reads entirely from i18n
// so all 8 locales stay in step.
const showExplainer = ref(false)
const explainerSteps = computed(() => [
  { n: 1, title: t('contractsView.explainer.s1t'), desc: t('contractsView.explainer.s1d') },
  { n: 2, title: t('contractsView.explainer.s2t'), desc: t('contractsView.explainer.s2d') },
  { n: 3, title: t('contractsView.explainer.s3t'), desc: t('contractsView.explainer.s3d') },
  { n: 4, title: t('contractsView.explainer.s4t'), desc: t('contractsView.explainer.s4d') },
])
const explainerNotes = computed(() => [
  t('contractsView.explainer.escrow'),
  t('contractsView.explainer.dispute'),
  t('contractsView.explainer.templates'),
  t('contractsView.explainer.zero'),
])

const tabs = computed(() => [
  { id: 'contracts', label: t('contractsView.tabs.contracts') },
  { id: 'templates', label: t('contractsView.tabs.templates', 'Templates') },   // CONTRACT SPINE P4 (tab hides itself server-dark)
  { id: 'analytics', label: t('contractsView.tabs.analytics') }
])
const activeTab = ref('contracts')

const drawerTabs = ['Overview', 'Repository', 'Criteria', 'Timeline'] as const
type DrawerTab = typeof drawerTabs[number]
const drawerTab = ref<DrawerTab>('Overview')
const drawerTabsWithLabels = computed(() => ([
  { id: 'Overview' as DrawerTab,   label: t('contractsView.drawer.tabs.overview') },
  { id: 'Repository' as DrawerTab, label: t('contractsView.drawer.tabs.repository') },
  { id: 'Criteria' as DrawerTab,   label: t('contractsView.drawer.tabs.criteria') },
  { id: 'Timeline' as DrawerTab,   label: t('contractsView.drawer.tabs.timeline') },
]))

// ─── Filters ─────────────────────────────────────────────────────────────────
const roleFilter = ref<'all' | 'client' | 'upgrader'>('all')
const searchQuery = ref('')
const hasActiveFilters = computed(
  () =>
    contractStore.statusFilter !== 'ALL' ||
    roleFilter.value !== 'all' ||
    searchQuery.value.trim().length > 0
)
function clearFilters() {
  roleFilter.value = 'all'
  searchQuery.value = ''
  contractStore.clearFilters()
}

// ─── Status helpers ───────────────────────────────────────────────────────────
// P5.1 (2026-05-08): ACCEPTED uses var(--nc-primary) so it cycles to
// sovereign red / custom-theme accent. The other 3 are semantic colors
// (amber=proposed, orange=pending-merge, green=completed) — intentionally
// NOT theme-cycled because they encode meaning, not brand.
const STATUS_COLORS: Record<string, string> = {
  PROPOSED: 'rgb(251,191,36)',
  ACCEPTED: 'var(--nc-primary, #00d2d2)',
  PENDING_MERGE: 'rgb(251,146,60)',
  COMPLETED: 'rgb(34,197,94)'
}
const STATUS_LABEL_KEYS: Record<string, string> = {
  PROPOSED: 'contractsView.statusLabel.proposed',
  ACCEPTED: 'contractsView.statusLabel.accepted',
  PENDING_MERGE: 'contractsView.statusLabel.pendingMerge',
  COMPLETED: 'contractsView.statusLabel.completed'
}

function statusColor(s: string) { return STATUS_COLORS[s] || '#8fa3be' }
function statusLabel(s: string) { return STATUS_LABEL_KEYS[s] ? t(STATUS_LABEL_KEYS[s]) : s }

const pipeline = computed(() => [
  { status: 'PROPOSED', short: t('contractsView.pipeline.proposed') },
  { status: 'ACCEPTED', short: t('contractsView.pipeline.accepted') },
  { status: 'PENDING_MERGE', short: t('contractsView.pipeline.review') },
  { status: 'COMPLETED', short: t('contractsView.pipeline.done') }
])
const pipelineOrder = ['PROPOSED', 'ACCEPTED', 'PENDING_MERGE', 'COMPLETED']
function pipelineIdx(s: string) { return pipelineOrder.indexOf(s) }

// ─── Stat cards ───────────────────────────────────────────────────────────────
const statusPills = computed(() => [
  { val: 'ALL' as const, label: t('contractsView.statusPills.all') },
  { val: 'PROPOSED' as const, label: t('contractsView.statusPills.proposed') },
  { val: 'ACCEPTED' as const, label: t('contractsView.statusPills.accepted') },
  { val: 'PENDING_MERGE' as const, label: t('contractsView.statusPills.pendingMerge') },
  { val: 'COMPLETED' as const, label: t('contractsView.statusPills.completed') }
])

// §TWOAGENT V0442: where the legacy list is retired, the tiles count the rail (it is the only list there is).
const railCounts = computed(() => railTileCounts(railItems.value))
/** §FESUITE: what the tiles and the header count is known only once its own list answered (the store's legacy list,
 *  or the rail where that list is retired); a retired list counts the rail, not an always-empty grid. */
const countsKnown = computed(() => contractStore.legacyRetired ? railRead.value : contractStore.loaded)
const listCount = computed(() => !countsKnown.value ? '—' : contractStore.legacyRetired ? railItems.value.length : contractStore.contracts.length)
const statCards = computed(() => contractStore.legacyRetired ? [
  { status: 'PROPOSED' as const, label: t('contractsView.statusLabel.proposed'), count: railCounts.value.proposed, color: STATUS_COLORS.PROPOSED, value: null },
  { status: 'ACCEPTED' as const, label: t('contractsView.statusLabel.accepted'), count: railCounts.value.accepted, color: STATUS_COLORS.ACCEPTED, value: null },
  { status: 'PENDING_MERGE' as const, label: t('contractsView.statusLabel.pendingMerge'), count: railCounts.value.inReview, color: STATUS_COLORS.PENDING_MERGE, value: null },
  { status: 'COMPLETED' as const, label: t('contractsView.statusLabel.completed'), count: railCounts.value.completed, color: STATUS_COLORS.COMPLETED, value: null },
] : [
  { status: 'PROPOSED' as const, label: t('contractsView.statusLabel.proposed'), count: contractStore.stats.proposed, color: STATUS_COLORS.PROPOSED, value: null },
  { status: 'ACCEPTED' as const, label: t('contractsView.statusLabel.accepted'), count: contractStore.stats.accepted, color: STATUS_COLORS.ACCEPTED, value: null },
  { status: 'PENDING_MERGE' as const, label: t('contractsView.statusLabel.pendingMerge'), count: contractStore.stats.pendingMerge, color: STATUS_COLORS.PENDING_MERGE, value: null },
  { status: 'COMPLETED' as const, label: t('contractsView.statusLabel.completed'), count: contractStore.stats.completed, color: STATUS_COLORS.COMPLETED, value: contractStore.stats.completedValue ? contractStore.stats.completedValue.toLocaleString(appLocale()) + ' ' + localCurrency.value : null }
])

// ─── Role chip ────────────────────────────────────────────────────────────────
function roleLabel(c: BackendContract): string {
  if (!activeAgentDid.value) return t('contractsView.roleChip.observer')
  if (c.client_agent_did === activeAgentDid.value) return t('contractsView.roleChip.client')
  if (c.upgrader_agent_did === activeAgentDid.value) return t('contractsView.roleChip.upgrader')
  return t('contractsView.roleChip.observer')
}
function roleChipClass(c: BackendContract): string {
  if (!activeAgentDid.value) return 'role-observer'
  if (c.client_agent_did === activeAgentDid.value) return 'role-client'
  if (c.upgrader_agent_did === activeAgentDid.value) return 'role-upgrader'
  return 'role-observer'
}

// ─── Action guards ────────────────────────────────────────────────────────────
function canAccept(c: BackendContract) {
  return (
    c.status === 'PROPOSED' &&
    activeAgentDid.value &&
    c.client_agent_did !== activeAgentDid.value
  )
}
function canSubmit(c: BackendContract) {
  return c.status === 'ACCEPTED' && c.upgrader_agent_did === activeAgentDid.value
}
function canApprove(c: BackendContract) {
  return c.status === 'PENDING_MERGE' && c.client_agent_did === activeAgentDid.value
}
function canMalpractice(c: BackendContract) {
  return (
    ['ACCEPTED', 'PENDING_MERGE'].includes(c.status) &&
    (c.client_agent_did === activeAgentDid.value || c.upgrader_agent_did === activeAgentDid.value)
  )
}

// ─── Repo short display ───────────────────────────────────────────────────────
function shortRepo(url: string): string {
  return url.replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '')
}

// ─── Date formatting ──────────────────────────────────────────────────────────
function fmtDate(d: string | null): string {
  if (!d) return '—'
  return new Date(d).toLocaleString(appLocale(), {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit'
  })
}

// ─── Clipboard ────────────────────────────────────────────────────────────────
async function copyToClipboard(text: string) {
  try {
    await navigator.clipboard.writeText(text)
  } catch { /* expected */ }
}

// ─── Drawer ───────────────────────────────────────────────────────────────────
// §BLOGSHOTS-FIX: keyed by ctrRef so spine-native rows (id === -1) open too.
function openDrawer(key: number | string) {
  drawerTab.value = 'Overview'
  contractStore.openDrawer(key)
}

const isPartyToActive = computed(() => {
  const c = contractStore.activeContract
  if (!c || !activeAgentDid.value) return false
  return c.client_agent_did === activeAgentDid.value || c.upgrader_agent_did === activeAgentDid.value
})

const activeCriteriaEntries = computed(() =>
  Object.entries(contractStore.activeContract?.acceptance_criteria || {})
)

// ─── Modal wiring ─────────────────────────────────────────────────────────────
const showCreate = ref(false)
const showAccept = ref(false)
const showSubmit = ref(false)
const showApprove = ref(false)
const showMalpractice = ref(false)
/* §FESUITE — the drawer is a dialog: focus moves into it and stays there, Escape closes it (unless a dialog opened
   from it is on top: that one closes first), and it does not outlive the page (the store is global, so a drawer
   left open came back, with the data it had then, on the next visit). */
const anyModalOpen = computed(() => showCreate.value || showAccept.value || showSubmit.value || showApprove.value || showMalpractice.value)
const drawerEl = ref<HTMLElement | null>(null)
useFocusTrap(drawerEl, { activeWhen: computed(() => !!(contractStore.drawerOpen && contractStore.activeContract) && !anyModalOpen.value) })
function onDrawerEsc(e: KeyboardEvent) {
  if (e.key === 'Escape' && contractStore.drawerOpen && !anyModalOpen.value) contractStore.closeDrawer()
}
onMounted(() => window.addEventListener('keydown', onDrawerEsc))
onBeforeUnmount(() => { window.removeEventListener('keydown', onDrawerEsc); contractStore.closeDrawer() })
const modalContract = ref<BackendContract | null>(null)

function openAccept(c: BackendContract) { modalContract.value = c; showAccept.value = true }
function openSubmit(c: BackendContract) { modalContract.value = c; showSubmit.value = true }
function openApprove(c: BackendContract) { modalContract.value = c; showApprove.value = true }
function openMalpractice(c: BackendContract) { modalContract.value = c; showMalpractice.value = true }

async function onCreated(id: number | string) { await reload(); openDrawer(id) }
async function onAccepted(id: number | string) { await reload(); openDrawer(id) }
async function onSubmitted(id: number | string) { await reload(); openDrawer(id) }
async function onCompleted(id: number | string) { await reload(); openDrawer(id) }

// ─── Analytics ────────────────────────────────────────────────────────────────
const stageBars = computed(() => {
  const total = Math.max(contractStore.stats.total, 1)
  return [
    { label: t('contractsView.statusLabel.proposed'), count: contractStore.stats.proposed, pct: Math.round((contractStore.stats.proposed / total) * 100), color: STATUS_COLORS.PROPOSED },
    { label: t('contractsView.statusLabel.accepted'), count: contractStore.stats.accepted, pct: Math.round((contractStore.stats.accepted / total) * 100), color: STATUS_COLORS.ACCEPTED },
    { label: t('contractsView.statusLabel.pendingMerge'), count: contractStore.stats.pendingMerge, pct: Math.round((contractStore.stats.pendingMerge / total) * 100), color: STATUS_COLORS.PENDING_MERGE },
    { label: t('contractsView.statusLabel.completed'), count: contractStore.stats.completed, pct: Math.round((contractStore.stats.completed / total) * 100), color: STATUS_COLORS.COMPLETED }
  ]
})

const myActivityBars = computed(() => {
  const did = activeAgentDid.value
  if (!did) return []
  const all = contractStore.contracts
  const asClient = all.filter(c => c.client_agent_did === did).length
  const asUpgrader = all.filter(c => c.upgrader_agent_did === did).length
  const myTotal = Math.max(asClient + asUpgrader, 1)
  return [
    { label: t('contractsView.analytics.asClient'), count: asClient, pct: Math.round((asClient / myTotal) * 100), color: 'rgb(251,191,36)' },
    { label: t('contractsView.analytics.asUpgrader'), count: asUpgrader, pct: Math.round((asUpgrader / myTotal) * 100), color: 'rgb(168,85,247)' }
  ]
})

// ─── Lifecycle ────────────────────────────────────────────────────────────────
// §FESUITE (V0575): fetchContracts reports a failed read in `error` and never throws, so a catch here never fired.
// With nothing on screen the list itself says the read failed (ReadFailedNotice); rows still on screen are the last
// read's, and the toast says the refresh failed.
async function reload() {
  await contractStore.fetchContracts()
  if (contractStore.error && contractStore.contracts.length) {
    uiStore.showError(t('contractsView.error.loadFailed'), t('contractsView.error.loadFailedMsg'))
  }
}

// §XHIREFE — replicas of cross-registry contracts for the ACTING agent.
// Best-effort: no acting agent (or no creds) ⇒ the strip stays hidden.
// §TWOAGENT V0442: every row the rail holds for the acting agent, split into what lives here and the couriers.
const railItems = ref<any[]>([])
/** §FESUITE (the loading sweep): the rail's own read answered for the acting agent. With no acting agent nothing is
 *  asked, and a failed read clears the rows: both keep the tiles at a dash, never "0". */
const railRead = ref(false)
const railFailed = ref(false)   // the rail was asked and gave no answer (not: no acting agent to ask for)
const replicaRows = computed(() => splitRailRows<any>(railItems.value).replicas)
const homeRows = computed(() => splitRailRows<any>(railItems.value).home)
const replicaOpen = ref<string | null>(null)
const homeOpen = ref<string | null>(null)
// the strip follows the acting agent: switching agents on this page reloads it (it loaded once, at mount)
// §FESUITE — and so does the board. The grid's "mine" half is asked for the acting agent; a page loaded before the
// console restored that agent (every fresh load: the restore is asynchronous) fetched only the public proposals, so a
// client never saw its own accepted or delivered contracts, and never the Approve button, until it pressed Refresh.
watch(activeAgentDid, (now, before) => {
  void loadReplicas()
  if (now && now !== before) void reload()
})
// §COCKPITDESK (2026-10-15): the rail is read as the acting agent; an answer that arrives after the agent changed is
// dropped (the latest read owns the strip), as the board's own fetch does
let railSeq = 0
async function loadReplicas() {
  // the rail is the ACTING agent's: with none there is nothing to ask (asking anyway was a 401 on every visit)
  const seq = ++railSeq
  railFailed.value = false
  if (!activeAgentDid.value) { railItems.value = []; railRead.value = false; return }
  try {
    const r = await contractsV2Api.mine({})
    if (seq !== railSeq) return
    railItems.value = r.items || []
    railRead.value = true
  } catch {
    if (seq !== railSeq) return
    railItems.value = []; railRead.value = false; railFailed.value = true
  }
}
function railRoleText(r: any): string {
  const role = railRole(r, activeAgentDid.value)
  return role === 'client' ? t('contractsView.roleChip.client') : role === 'provider' ? t('contractsView.roleChip.upgrader') : ''
}

onMounted(async () => {
  // §AGENTDISC #195 — Discovery's Draft-contract CTA: open the EXISTING create modal.
  if (_useRouteAgentdisc().query.create === '1') showCreate.value = true

  void loadReplicas()
  await reload()
})
</script>

<style scoped>
/* §XHIREFE — cross-registry offers strip */
/* §TWOAGENT V0441: the strip (§XHIREFE, added after the width rule above) ran from the sidebar to the viewport edge
   while every sibling sat in the 1280px column with a 32px inset; its margins put its edges on the tiles' edges. */
.ctr-replica-strip { margin: 14px max(32px, calc((100% - 1216px) / 2)); padding: 12px 14px; border-radius: 10px;
  border: 1px solid rgba(55, 201, 255, 0.3); background: rgba(55, 201, 255, 0.05); }
.ctr-replica-head { display: flex; align-items: center; gap: 8px; font-size: .78rem;
  font-weight: 700; letter-spacing: .05em; text-transform: uppercase; opacity: .85; margin-bottom: 6px; }
.ctr-replica-row { border-top: 1px dotted rgba(128, 128, 128, .2); }
.ctr-replica-btn { display: flex; align-items: center; gap: 10px; width: 100%; min-height: 44px;
  padding: 6px 4px; border: none; background: none; color: inherit; cursor: pointer; text-align: left; }
.ctr-replica-chip { display: inline-flex; align-items: center; gap: 4px; padding: 2px 9px;
  border-radius: 999px; font-size: .68rem; font-weight: 700;
  background: rgba(55, 201, 255, 0.12); border: 1px solid rgba(55, 201, 255, 0.35); }
.ctr-replica-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ctr-replica-amt { font-variant-numeric: tabular-nums; font-weight: 700; }
.ctr-replica-st { font-size: .7rem; opacity: .7; text-transform: uppercase; }
.ctr-home-chip { background: rgba(34, 197, 94, 0.12); border-color: rgba(34, 197, 94, 0.4); }
.ctr-home-role, .ctr-home-with { font-size: .72rem; opacity: .8; white-space: nowrap; }
.ctr-home-note { margin: 2px 4px 10px; font-size: .78rem; line-height: 1.5; opacity: .85; }
.ctr-replica-head + .ctr-replica-row ~ .ctr-replica-head, .ctr-replica-row + .ctr-replica-head { margin-top: 10px; }

/* ─── Theme tokens (mirrors AdminCanaries Phase 11 polish, 2026-05-06) ──────
   View-local CSS variables aliased to system theme tokens so `neural`/`sovereign`
   theme switches propagate. Semantic status colors (success / warning / danger)
   stay fixed across themes — they mean specific things.
*/
.contracts-root {
  position: relative;
  min-height: 100vh;
  padding: 0 0 32px 0;
  font-family: system-ui, -apple-system, sans-serif;

  --cc-accent: var(--nc-primary, #00d2d2);
  --cc-accent-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --cc-accent-bright: var(--nc-primary-bright, #00e5e5);

  --cc-success: var(--nc-success, #00ff88);
  --cc-warning: var(--nc-warning, #ff9500);
  --cc-danger:  var(--nc-danger,  #ff3366);
  --cc-purple:  #b87aff;

  --cc-surface: var(--nc-deep, #0a0d16);
  --cc-surface-2: var(--nc-surface, #111827);
  --cc-border: rgba(var(--cc-accent-rgb), 0.18);
  --cc-text-bright: var(--nc-text-primary, #e8eaed);
  --cc-text-muted: var(--nc-text-muted, #6b7785);
  --cc-mono: 'IBM Plex Mono', 'Fira Code', monospace;

  /* §pass50.4 — opaque background removed; DashboardLayout's <ViewAmbient> paints.
     Was: background: var(--cc-surface) — replaced with transparent + z-index lift. */
  z-index: 1;
  color: var(--cc-text-bright);
  transition: background 240ms ease, color 240ms ease;
}

/* ─── Ambient background ─────────────────────────────────────────────────── */
.cc-ambient {
  position: fixed; inset: 0; z-index: 0; pointer-events: none; overflow: hidden;
}
.cc-grid {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(var(--cc-accent-rgb), 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--cc-accent-rgb), 0.03) 1px, transparent 1px);
  background-size: 60px 60px;
  /* §DESKCHROME 2026-08-28: grid is STATIC — perpetual drift removed (Commander) */
}
.cc-scan {
  position: absolute; inset: 0;
  background: repeating-linear-gradient(
    180deg,
    transparent 0, transparent 3px,
    rgba(var(--cc-accent-rgb), 0.025) 3px, rgba(var(--cc-accent-rgb), 0.025) 4px
  );
}
.cc-glow {
  position: absolute; border-radius: 50%; filter: blur(120px); opacity: 0.18;
}
.cc-glow-1 { width: 480px; height: 480px; background: rgba(var(--cc-accent-rgb), 0.6); top: -100px; right: -100px; }
.cc-glow-2 { width: 360px; height: 360px; background: rgba(var(--cc-purple-rgb, 184, 122, 255), 0.4); bottom: -80px; left: -80px; }

/* ─── Hero strip ─────────────────────────────────────────────────────────── */
/* ── "How contracts work" explainer ─────────────────────────────────────── */
.ctr-ex-toggle {
  margin-top: 0.9rem; background: transparent; border: 1px solid var(--border, rgba(148,163,184,.35));
  color: var(--text-muted, #94a3b8); border-radius: 999px; padding: 0.32rem 0.85rem;
  font-size: 0.78rem; font-weight: 600; cursor: pointer; display: inline-flex;
  align-items: center; gap: 0.4rem; transition: border-color .15s, color .15s;
}
.ctr-ex-toggle:hover { color: var(--text, #e2e8f0); border-color: var(--accent, #6366f1); }
.ctr-ex-toggle:focus-visible { outline: 2px solid var(--accent, #6366f1); outline-offset: 2px; }
.ctr-ex-caret { display: inline-block; transition: transform .18s ease; }
.ctr-ex-caret.open { transform: rotate(90deg); }

.ctr-ex {
  max-width: 1280px; margin: 0 auto 1.25rem; padding: 1.15rem 1.35rem;
  border: 1px solid var(--border, rgba(148,163,184,.25));
  border-radius: 14px; background: var(--surface-2, rgba(30,41,59,.35));
}
.ctr-ex__h { font-size: 0.95rem; font-weight: 700; margin: 0 0 0.9rem; color: var(--text, #e2e8f0); }
.ctr-ex__steps {
  list-style: none; margin: 0 0 1rem; padding: 0;
  display: grid; gap: 0.85rem; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
}
.ctr-ex__step { display: flex; gap: 0.6rem; align-items: flex-start; }
.ctr-ex__num {
  flex: 0 0 auto; width: 1.55rem; height: 1.55rem; border-radius: 50%;
  display: grid; place-items: center; font-size: 0.76rem; font-weight: 700;
  background: var(--accent-soft, rgba(99,102,241,.15)); color: var(--accent, #818cf8);
}
.ctr-ex__st { font-size: 0.84rem; font-weight: 650; color: var(--text, #e2e8f0); }
.ctr-ex__sd { font-size: 0.79rem; line-height: 1.45; margin: 0.15rem 0 0; color: var(--text-muted, #94a3b8); }
.ctr-ex__notes { display: grid; gap: 0.5rem; border-top: 1px solid var(--border, rgba(148,163,184,.18)); padding-top: 0.9rem; }
.ctr-ex__note {
  margin: 0; font-size: 0.79rem; line-height: 1.5; color: var(--text-muted, #94a3b8);
  display: flex; gap: 0.55rem; align-items: baseline;
}
.ctr-ex__dot {
  flex: 0 0 auto; width: 5px; height: 5px; border-radius: 50%;
  background: var(--accent, #818cf8); transform: translateY(-2px);
}
@media (max-width: 640px) {
  .ctr-ex { margin-left: 0.75rem; margin-right: 0.75rem; padding: 1rem; }
  .ctr-ex__steps { grid-template-columns: 1fr; }
}

.cc-hero {
  position: relative; z-index: 1;
  padding: 48px 32px 24px;
}
.cc-hero-inner { max-width: 1280px; margin: 0 auto; }
.cc-chip-hero {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--cc-mono); font-size: 10px; font-weight: 600;
  letter-spacing: 0.18em; color: var(--cc-accent);
  padding: 4px 12px;
  border: 1px solid rgba(var(--cc-accent-rgb), 0.25);
  border-radius: 99px; margin-bottom: 14px;
  background: rgba(var(--cc-accent-rgb), 0.04);
}
.cc-chip-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--cc-accent);
  box-shadow: 0 0 8px var(--cc-accent);
  animation: ccPulse 1.6s ease-in-out infinite;
}
@keyframes ccPulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
.cc-h1 {
  font-family: 'Orbitron', 'IBM Plex Sans', sans-serif;
  font-weight: 800; font-size: 34px; letter-spacing: 0.02em;
  margin: 0 0 10px; color: var(--cc-text-bright); line-height: 1.15;
}
.cc-accent { color: var(--cc-accent); text-shadow: 0 0 14px rgba(var(--cc-accent-rgb), 0.45); }
.cc-lead { color: var(--cc-text-muted); font-size: 14px; max-width: 760px; line-height: 1.7; margin: 0; }

/* All inner sections need to render above the ambient layer */
.cmd-bar, .no-agent-banner, .tab-bar, .stat-grid, .filter-bar, .contract-grid,
.empty-state, .loading-state, .drawer-overlay, .ctr-replica-strip {
  position: relative; z-index: 1;
}
.cmd-bar, .no-agent-banner, .tab-bar, .stat-grid, .filter-bar, .contract-grid,
.empty-state, .loading-state {
  max-width: 1280px;
  margin-left: auto;
  margin-right: auto;
}
.cmd-bar { padding: 0 32px; }
.no-agent-banner, .tab-bar, .stat-grid, .filter-bar, .contract-grid,
.empty-state, .loading-state { padding-left: 32px; padding-right: 32px; }

/* ─── Command Bar ─────────────────────────────────────────────────────────── */
.cmd-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.25rem;
  gap: 1rem;
  flex-wrap: wrap;
}
.cmd-bar__left { display: flex; align-items: center; gap: 0.85rem; }
.cmd-bar__icon {
  width: 40px; height: 40px;
  background: rgba(var(--cc-accent-rgb),0.1);
  border: 1px solid rgba(var(--cc-accent-rgb),0.25);
  border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  font-size: 1.15rem;
  color: var(--cc-accent);
  flex-shrink: 0;
}
.cmd-bar__title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--cc-text-bright);
  margin: 0;
}
.cmd-bar__sub {
  font-size: 0.78rem;
  color: var(--cc-text-muted);
  margin: 0;
}
.cmd-bar__right { display: flex; align-items: center; gap: 0.6rem; }

.cmd-btn {
  display: inline-flex; align-items: center; gap: 0.4rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem; font-weight: 600;
  letter-spacing: 0.1em; text-transform: uppercase;
  padding: 0.55rem 1rem;
  border-radius: 6px; border: 1px solid transparent;
  cursor: pointer; transition: all 0.15s;
  white-space: nowrap;
}
.cmd-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.cmd-btn--primary {
  background: var(--cc-accent); color: var(--cc-surface); border-color: var(--cc-accent);
}
.cmd-btn--primary:hover:not(:disabled) { background: rgba(var(--cc-accent-rgb),0.85); }
.cmd-btn--ghost {
  background: transparent; color: var(--cc-text-secondary, #8fa3be); border-color: rgba(var(--cc-accent-rgb),0.2);
}
.cmd-btn--ghost:hover:not(:disabled) { background: rgba(var(--cc-accent-rgb),0.08); color: var(--cc-accent); }

/* ─── No-agent banner ────────────────────────────────────────────────────── */
.no-agent-banner {
  background: rgba(251,191,36,0.07);
  border: 1px solid rgba(251,191,36,0.2);
  border-radius: 8px;
  color: rgba(251,191,36,0.85);
  padding: 0.65rem 1rem;
  font-size: 0.82rem;
  margin-bottom: 1rem;
}

/* ─── Tabs ───────────────────────────────────────────────────────────────── */
.tab-bar {
  display: flex;
  gap: 0.25rem;
  border-bottom: 1px solid rgba(var(--cc-accent-rgb),0.1);
  margin-bottom: 1.25rem;
}
.tab-btn {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem; font-weight: 600;
  letter-spacing: 0.1em; text-transform: uppercase;
  padding: 0.6rem 1.2rem;
  background: transparent; border: none;
  border-bottom: 2px solid transparent;
  color: var(--cc-text-muted); cursor: pointer;
  transition: all 0.15s;
  margin-bottom: -1px;
}
.tab-btn:hover { color: var(--cc-text-secondary, #8fa3be); }
.tab-btn.active {
  color: var(--cc-accent);
  border-bottom-color: var(--cc-accent);
}

/* ─── Stat cards ─────────────────────────────────────────────────────────── */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.75rem;
  margin-bottom: 1.25rem;
}
@media (max-width: 900px) { .stat-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 520px) { .stat-grid { grid-template-columns: 1fr 1fr; } }

.stat-card {
  background: var(--cc-surface-2);
  border: 1px solid rgba(var(--cc-accent-rgb),0.1);
  border-radius: 10px;
  padding: 1rem 1.1rem;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
  position: relative;
  overflow: hidden;
}
.stat-card:hover { border-color: rgba(var(--accent, 0,210,210), 0.35); background: rgba(255,255,255,0.02); }
.stat-card.active { border-color: var(--accent); background: rgba(var(--cc-accent-rgb),0.04); }
.stat-card__dot {
  width: 8px; height: 8px; border-radius: 50%;
  margin-bottom: 0.5rem;
}
.stat-card__count {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 1.65rem; font-weight: 700;
  color: var(--cc-text-bright);
}
.stat-card__label {
  font-size: 0.72rem; color: var(--cc-text-muted);
  font-family: 'IBM Plex Mono', monospace;
  letter-spacing: 0.08em; text-transform: uppercase;
  margin-top: 0.15rem;
}
.stat-card__value {
  font-size: 0.75rem; color: rgb(34,197,94);
  font-family: 'IBM Plex Mono', monospace;
  margin-top: 0.2rem;
}

/* ─── Filter bar ─────────────────────────────────────────────────────────── */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 1.25rem;
  flex-wrap: wrap;
}
.filter-pills { display: flex; gap: 0.4rem; flex-wrap: wrap; }
.pill {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.67rem; font-weight: 600;
  letter-spacing: 0.08em; text-transform: uppercase;
  padding: 0.3rem 0.75rem;
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(var(--cc-accent-rgb),0.15);
  border-radius: 20px;
  color: var(--cc-text-muted); cursor: pointer;
  transition: all 0.12s;
}
.pill:hover { color: var(--cc-accent); border-color: rgba(var(--cc-accent-rgb),0.35); }
.pill.active {
  background: rgba(var(--cc-accent-rgb),0.12);
  border-color: rgba(var(--cc-accent-rgb),0.5);
  color: var(--cc-accent);
}
.filter-group {
  display: flex; align-items: center; gap: 0.4rem;
}
.filter-group--grow { flex: 1; min-width: 200px; }
.filter-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.67rem; text-transform: uppercase;
  letter-spacing: 0.08em; color: var(--cc-text-muted);
  white-space: nowrap;
}
.filter-select, .filter-input {
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(var(--cc-accent-rgb),0.15);
  border-radius: 6px;
  color: #c8d6e8;
  padding: 0.35rem 0.65rem;
  font-size: 0.82rem;
  outline: none;
}
.filter-input { width: 100%; }
.filter-select option { background: var(--cc-surface-2); }
.filter-select:focus, .filter-input:focus { border-color: rgba(var(--cc-accent-rgb),0.4); }
.filter-clear {
  font-size: 0.72rem; color: var(--cc-text-muted);
  background: none; border: none; cursor: pointer;
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
}
.filter-clear:hover { color: rgb(239,68,68); }

/* ─── Empty / loading ────────────────────────────────────────────────────── */
.empty-state {
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  padding: 4rem 2rem;
  gap: 1rem;
}
.empty-state__icon { font-size: 2.5rem; color: #1a2535; }
.empty-state__msg { color: var(--cc-text-muted); font-size: 0.9rem; }

/* ─── Contract grid ──────────────────────────────────────────────────────── */
.contract-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.85rem;
}
@media (max-width: 860px) { .contract-grid { grid-template-columns: 1fr; } }

.contract-card {
  background: var(--cc-surface-2);
  border: 1px solid rgba(var(--cc-accent-rgb),0.1);
  border-radius: 10px;
  padding: 1rem 1.1rem;
  cursor: pointer;
  transition: border-color 0.15s, transform 0.1s;
  display: flex; flex-direction: column; gap: 0.6rem;
}
.contract-card:hover { border-color: rgba(var(--cc-accent-rgb),0.3); transform: translateY(-1px); }
.contract-card.status-accepted { border-left: 3px solid rgba(var(--cc-accent-rgb),0.45); }
.contract-card.status-pending-merge { border-left: 3px solid rgba(251,146,60,0.45); }
.contract-card.status-completed { border-left: 3px solid rgba(34,197,94,0.3); }
.contract-card.status-proposed { border-left: 3px solid rgba(251,191,36,0.35); }

.cc-header {
  display: flex; align-items: center; justify-content: space-between;
}
.cc-meta { display: flex; align-items: center; gap: 0.5rem; }
.cc-status-dot {
  width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
}
.contract-card.status-accepted .cc-status-dot { animation: pulse-cyan 2s ease-in-out infinite; }
@keyframes pulse-cyan {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
.cc-id-btn { background: none; border: 0; padding: 0; font: inherit; color: inherit; cursor: pointer; text-align: left; }
.cc-id-btn:focus-visible { outline: 2px solid rgba(var(--nc-primary-rgb), 0.8); outline-offset: 2px; border-radius: 3px; }
.cc-id {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.75rem; color: var(--cc-text-muted);
}
.cc-status-badge {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem; font-weight: 600;
  letter-spacing: 0.08em; text-transform: uppercase;
  padding: 0.18rem 0.55rem;
  border-radius: 10px;
  border: 1px solid;
}
.cc-role-chip {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem; font-weight: 700;
  letter-spacing: 0.08em; text-transform: uppercase;
  padding: 0.18rem 0.55rem; border-radius: 10px;
}
.role-client { background: rgba(251,191,36,0.12); color: rgb(251,191,36); }
.role-upgrader { background: rgba(168,85,247,0.12); color: rgb(168,85,247); }
.role-observer { background: rgba(255,255,255,0.05); color: var(--cc-text-muted); }

.cc-scope {
  font-size: 0.84rem; color: #c8d6e8; line-height: 1.45; margin: 0;
}
.cc-repo {
  font-size: 0.75rem; margin: 0;
  display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap;
}
.cc-repo a {
  color: rgba(var(--cc-accent-rgb),0.7); text-decoration: none;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
}
.cc-repo a:hover { color: var(--cc-accent); }
.cc-branch {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem; color: var(--cc-text-muted);
  background: rgba(255,255,255,0.05);
  border-radius: 4px; padding: 0.1rem 0.35rem;
}

/* Pipeline bar */
.cc-pipeline {
  display: flex; align-items: center;
  gap: 0; margin: 0.15rem 0;
}
.cc-pipeline-stage {
  display: flex; align-items: center;
  flex: 1; min-width: 0;
}
.cc-pip-dot {
  width: 10px; height: 10px;
  border-radius: 50%;
  border: 1.5px solid rgba(255,255,255,0.12);
  background: rgba(255,255,255,0.05);
  flex-shrink: 0;
  transition: all 0.2s;
}
.cc-pipeline-stage.done .cc-pip-dot {
  background: var(--cc-accent);
  border-color: var(--cc-accent);
}
.cc-pipeline-stage.current .cc-pip-dot {
  background: rgba(var(--cc-accent-rgb),0.4);
  border-color: var(--cc-accent);
  box-shadow: 0 0 6px rgba(var(--cc-accent-rgb),0.4);
}
.cc-pip-label {
  font-size: 0.6rem; color: #2d3f55;
  font-family: 'IBM Plex Mono', monospace;
  display: none;
}
.cc-pipeline-stage.done .cc-pip-label,
.cc-pipeline-stage.current .cc-pip-label { display: block; margin-left: 0.25rem; color: var(--cc-text-muted); }
.cc-pip-line {
  flex: 1; height: 1px;
  background: rgba(255,255,255,0.07);
}
.cc-pipeline-stage.done .cc-pip-line { background: rgba(var(--cc-accent-rgb),0.4); }

.cc-footer {
  display: flex; align-items: center; justify-content: space-between; margin-top: 0.2rem;
}
.cc-payment { display: flex; align-items: baseline; gap: 0.3rem; }
.cc-avt {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 1rem; font-weight: 700;
  color: var(--cc-accent);
}
.cc-avt-unit { font-size: 0.7rem; color: var(--cc-text-muted); font-family: 'IBM Plex Mono', monospace; }

.cc-actions { display: flex; gap: 0.4rem; }
.cc-btn {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem; font-weight: 600;
  letter-spacing: 0.08em; text-transform: uppercase;
  padding: 0.28rem 0.7rem;
  border-radius: 5px; border: 1px solid transparent;
  cursor: pointer; transition: all 0.12s;
}
.cc-btn--cyan { background: rgba(var(--cc-accent-rgb),0.1); color: var(--cc-accent); border-color: rgba(var(--cc-accent-rgb),0.3); }
.cc-btn--cyan:hover { background: rgba(var(--cc-accent-rgb),0.2); }
.cc-btn--amber { background: rgba(251,191,36,0.1); color: rgb(251,191,36); border-color: rgba(251,191,36,0.3); }
.cc-btn--amber:hover { background: rgba(251,191,36,0.2); }
.cc-btn--green { background: rgba(34,197,94,0.1); color: rgb(34,197,94); border-color: rgba(34,197,94,0.3); }
.cc-btn--green:hover { background: rgba(34,197,94,0.2); }
.cc-btn--red { background: rgba(239,68,68,0.1); color: rgb(239,68,68); border-color: rgba(239,68,68,0.3); }
.cc-btn--red:hover { background: rgba(239,68,68,0.2); }

/* ─── Drawer ────────────────────────────────────────────────────────────── */
.drawer-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.5);
  z-index: 9800;
  display: flex; justify-content: flex-end;
}
.drawer {
  width: min(480px, 96vw);
  height: 100vh;
  background: var(--cc-surface-2);
  border-left: 1px solid rgba(var(--cc-accent-rgb),0.15);
  display: flex; flex-direction: column;
  overflow: hidden;
}
.drawer-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 1.25rem 1.25rem 0.85rem;
  border-bottom: 1px solid rgba(var(--cc-accent-rgb),0.1);
}
.drawer-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.95rem; font-weight: 700;
  color: var(--cc-text-bright); margin-right: 0.75rem;
}
.drawer-status-badge {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase;
}
.drawer-tabs {
  display: flex; gap: 0.15rem;
  padding: 0 1.25rem;
  border-bottom: 1px solid rgba(var(--cc-accent-rgb),0.08);
}
.drawer-tab {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem; font-weight: 600;
  letter-spacing: 0.08em; text-transform: uppercase;
  padding: 0.55rem 0.85rem;
  background: transparent; border: none;
  border-bottom: 2px solid transparent;
  color: var(--cc-text-muted); cursor: pointer;
  transition: all 0.12s;
  margin-bottom: -1px;
}
.drawer-tab:hover { color: var(--cc-text-secondary, #8fa3be); }
.drawer-tab.active { color: var(--cc-accent); border-bottom-color: var(--cc-accent); }
.drawer-body {
  flex: 1; overflow-y: auto;
  padding: 1.1rem 1.25rem;
}
.drawer-footer {
  padding: 0.85rem 1.25rem;
  border-top: 1px solid rgba(var(--cc-accent-rgb),0.1);
  display: flex; gap: 0.6rem; flex-wrap: wrap;
}
.drawer-link {
  display: block; margin-top: 0.5rem;
  color: rgba(var(--cc-accent-rgb),0.85); font-size: 0.8rem;
  font-family: 'IBM Plex Mono', monospace;
  word-break: break-all; line-height: 1.5;
}
.drawer-empty {
  color: var(--cc-text-muted); font-size: 0.82rem; margin-top: 0.5rem;
}

/* ─── Re-use tp-row in scoped ─────────────────────────────────────────────── */
:deep(.tp-row) {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.45rem 0;
  border-bottom: 1px solid rgba(var(--cc-accent-rgb),0.07);
}
:deep(.tp-row:last-child) { border-bottom: none; }
:deep(.tp-row__label) {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.67rem; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--cc-text-muted); flex-shrink: 0; padding-top: 2px;
}
:deep(.tp-row__value) { color: #c8d6e8; font-size: 0.84rem; text-align: right; word-break: break-all; }
:deep(.tp-row__value--mono) { font-family: 'IBM Plex Mono', monospace; font-size: 0.77rem; }
:deep(.tp-row__value--big) { font-size: 1.05rem; font-weight: 700; color: var(--cc-accent); }
:deep(.tp-label) {
  display: block;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem; font-weight: 600;
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--cc-text-muted); margin-bottom: 0.35rem;
}

/* ─── Timeline ───────────────────────────────────────────────────────────── */
.timeline { display: flex; flex-direction: column; gap: 0; padding: 0.5rem 0; }
.tl-item {
  display: flex; align-items: flex-start; gap: 0.85rem;
  position: relative; padding-bottom: 1.25rem;
}
.tl-item:last-child { padding-bottom: 0; }
.tl-item:not(:last-child)::before {
  content: '';
  position: absolute;
  left: 7px; top: 16px;
  width: 1px; bottom: 0;
  background: rgba(var(--cc-accent-rgb),0.12);
}
.tl-dot {
  width: 15px; height: 15px; border-radius: 50%; flex-shrink: 0;
  background: rgba(255,255,255,0.05);
  border: 1.5px solid rgba(var(--cc-accent-rgb),0.15);
  margin-top: 2px;
}
.tl-dot.done { background: var(--cc-accent); border-color: var(--cc-accent); }
.tl-content { display: flex; flex-direction: column; gap: 0.15rem; }
.tl-label { font-size: 0.84rem; color: #c8d6e8; }
.tl-date { font-size: 0.73rem; color: var(--cc-text-muted); font-family: 'IBM Plex Mono', monospace; }

/* ─── Analytics ─────────────────────────────────────────────────────────── */
.analytics-panel { padding: 0.25rem 0; }
.analytics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 0.85rem;
}
.an-card {
  background: var(--cc-surface-2);
  border: 1px solid rgba(var(--cc-accent-rgb),0.1);
  border-radius: 10px;
  padding: 1.1rem 1.25rem;
}
.an-card__title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem; font-weight: 600;
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--cc-accent);
  margin: 0 0 1rem;
}
.an-bars { display: flex; flex-direction: column; gap: 0.7rem; }
.an-bar-row { display: flex; align-items: center; gap: 0.6rem; }
.an-bar-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.67rem; color: var(--cc-text-muted);
  width: 100px; flex-shrink: 0;
}
.an-bar-track {
  flex: 1; height: 6px;
  background: rgba(255,255,255,0.05);
  border-radius: 3px; overflow: hidden;
}
.an-bar-fill {
  height: 100%; border-radius: 3px;
  transition: width 0.5s cubic-bezier(0.4,0,0.2,1);
}
.an-bar-count {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem; color: #c8d6e8;
  width: 24px; text-align: right;
}
.an-stats { display: flex; flex-direction: column; gap: 0.6rem; }
.an-stat {
  display: flex; justify-content: space-between; align-items: center;
  padding: 0.4rem 0;
  border-bottom: 1px solid rgba(var(--cc-accent-rgb),0.06);
}
.an-stat:last-child { border-bottom: none; }
.an-stat__label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--cc-text-muted);
}
.an-stat__val {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.85rem; font-weight: 700; color: var(--cc-text-bright);
}
.an-stat__val.cyan { color: var(--cc-accent); }
.an-stat__val.green { color: rgb(34,197,94); }
.an-stat__val.amber { color: rgb(251,191,36); }

/* ─── Drawer slide animation ─────────────────────────────────────────────── */
.drawer-enter-active,
.drawer-leave-active { transition: opacity 0.2s ease; }
.drawer-enter-active .drawer,
.drawer-leave-active .drawer { transition: transform 0.22s cubic-bezier(0.4,0,0.2,1); }
.drawer-enter-from { opacity: 0; }
.drawer-enter-from .drawer { transform: translateX(100%); }
.drawer-leave-to { opacity: 0; }
.drawer-leave-to .drawer { transform: translateX(100%); }

/* ─── Spinner ────────────────────────────────────────────────────────────── */
.mini-spin {
  display: inline-block;
  width: 13px; height: 13px;
  border: 2px solid rgba(var(--cc-accent-rgb),0.25);
  border-top-color: var(--cc-accent);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* §2026-06-07 v2j — DESIGN-LANGUAGE house card. De-greys the flat --cc-surface-2
   (#111827) boxes → subtle primary tint + sheen + hairline + blur + soft shadow.
   Placed last so it overrides the per-class `background: var(--cc-surface-2)`
   (same specificity → later wins; no !important). Ref:
   PRODUCTION_DOCS/03_SERVICES/Frontend/Design_Language.md (Commander). */
.stat-card, .contract-card, .an-card, .drawer {
  background:
    linear-gradient(168deg, rgba(255,255,255,0.09), rgba(255,255,255,0.025) 46%, rgba(255,255,255,0.004) 100%),
    rgba(10, 14, 24, 0.45);
  border: 1px solid rgba(var(--cc-accent-rgb), 0.24);
  backdrop-filter: blur(16px) saturate(1.12);
  -webkit-backdrop-filter: blur(16px) saturate(1.12);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.08), 0 20px 46px -24px rgba(0,0,0,0.95);
}
.stat-card, .contract-card, .an-card { border-radius: 12px; }
/* keep the slide-in drawer flush to the right edge */
.drawer { border-radius: 14px 0 0 14px; }
.contract-card:hover, .stat-card:hover, .an-card:hover {
  background:
    linear-gradient(168deg, rgba(255,255,255,0.11), rgba(255,255,255,0.03) 46%, rgba(255,255,255,0.006) 100%),
    rgba(12, 17, 28, 0.5);
  border-color: rgba(var(--cc-accent-rgb), 0.42);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.09), 0 24px 52px -22px rgba(0,0,0,0.95);
  transform: translateY(-3px);
}
.contract-card, .stat-card, .an-card { transition: background .18s ease, border-color .18s ease, box-shadow .18s ease, transform .18s ease; }
/* §2026-06-07 v2k — inline monochrome icons replacing the lightning/clipboard emoji (no-emoji rule) */
.cc-inline-ic { width: 1em; height: 1em; display: inline-block; vertical-align: -0.15em; flex-shrink: 0; }
/* ═══ §v0003 polish (2 passes) ═══ */
/* pass 1 — hero stat numbers: tabular + per-value glow */
.stat-card__count { font-variant-numeric: tabular-nums; letter-spacing: -0.01em; text-shadow: 0 0 18px color-mix(in srgb, currentColor 22%, transparent); }
/* pass 2 — stat-card top accent line (lights on hover) + keyboard focus ring */
.stat-card { position: relative; overflow: hidden; }
.stat-card::before { content:''; position:absolute; top:0; left:14px; right:14px; height:1px; background: linear-gradient(90deg, transparent, rgba(var(--cc-accent-rgb),0.5), transparent); opacity:0.5; transition: opacity .18s ease; }
.stat-card:hover::before { opacity: 1; }
.contracts-root :is(button, input, select, [tabindex]):focus-visible { outline: 2px solid rgba(var(--cc-accent-rgb), 0.55); outline-offset: 2px; border-radius: 6px; }
</style>
