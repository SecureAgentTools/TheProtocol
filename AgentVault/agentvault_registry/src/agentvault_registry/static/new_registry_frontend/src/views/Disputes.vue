<template>
  <div class="drc-view">

    <!-- Ambient background layer (matches AdminCanaries) -->
    <div class="drc-ambient" aria-hidden="true">
      <div class="drc-grid"></div>
      <div class="drc-scan"></div>
      <div class="drc-glow drc-glow-1"></div>
      <div class="drc-glow drc-glow-2"></div>
    </div>

    <!-- Hero strip — mirrors canary hero pattern -->
    <section class="drc-hero">
      <div class="drc-hero-inner">
        <div class="drc-chip-hero"><span class="drc-chip-dot"></span>{{ t('disputesView.hero.chip') }}</div>
        <h1 class="drc-h1">
          {{ t('disputesView.hero.h1a') }}<span class="drc-accent">{{ t('disputesView.hero.h1Accent') }}</span>{{ t('disputesView.hero.h1b') }}
        </h1>
        <p class="drc-lead">
          {{ t('disputesView.hero.lead') }}
        </p>
      </div>
    </section>

    <!-- ── Page Header ──────────────────────────────────────────────────────── -->
    <div class="drc-header">
      <div class="drc-header__left">
        <h2 class="drc-title" data-tour="dsp-hero">{{ t('disputesView.title') }}</h2>
        <p class="drc-subtitle">{{ t('disputesView.subtitle') }}</p>
      </div>
      <div class="drc-header__right">
        <div class="drc-tabs" data-tour="dsp-tabs" role="tablist">
          <button type="button" role="tab" :aria-selected="activeTab === 'disputes'" :class="['drc-tab', activeTab === 'disputes'  && 'drc-tab--active']" @click="activeTab = 'disputes'">{{ t('disputesView.tabs.disputes') }}</button>
          <button type="button" role="tab" :aria-selected="activeTab === 'analytics'" :class="['drc-tab', activeTab === 'analytics' && 'drc-tab--active']" data-tour="dsp-analytics" @click="activeTab = 'analytics'">{{ t('disputesView.tabs.analytics') }}</button>
        </div>
      </div>
    </div>

    <!-- ── Analytics View ──────────────────────────────────────────────────── -->
    <DisputeAnalytics v-if="activeTab === 'analytics'" />

    <!-- ── Disputes View ───────────────────────────────────────────────────── -->
    <div v-else>

      <!-- Stat Cards -->
      <div class="drc-stats">
        <div class="drc-stat-card" data-tour="dsp-stats">
          <div class="drc-stat-card__accent" style="background:var(--drc-orange)"></div>
          <div class="drc-stat-card__body">
            <div class="drc-stat-card__icon" style="color:var(--drc-orange)">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
            </div>
            <div>
              <div class="drc-stat-card__value" data-testid="dsp-total">{{ statsRead ? stats.total_disputes + (stats.capped ? '+' : '') : '—' }}</div>
              <div class="drc-stat-card__label">{{ t('disputesView.stats.total') }}</div>
            </div>
          </div>
        </div>

        <div class="drc-stat-card">
          <div class="drc-stat-card__accent" style="background:var(--drc-red)"></div>
          <div class="drc-stat-card__body">
            <div class="drc-stat-card__icon" style="color:var(--drc-red)">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/></svg>
            </div>
            <div>
              <div class="drc-stat-card__value" style="color:var(--drc-red)">{{ statsRead ? stats.open_disputes : '—' }}</div>
              <div class="drc-stat-card__label">{{ t('disputesView.stats.open') }}</div>
            </div>
          </div>
        </div>

        <div class="drc-stat-card">
          <div class="drc-stat-card__accent" style="background:var(--drc-green)"></div>
          <div class="drc-stat-card__body">
            <div class="drc-stat-card__icon" style="color:var(--drc-green)">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
            </div>
            <div>
              <div class="drc-stat-card__value" style="color:var(--drc-green)" data-testid="drc-decided"
                   :title="statsRead ? tp('disputesView.stats.decidedHint', '{u} upheld · {d} dismissed', { u: stats.resolved_disputes, d: stats.dismissed_disputes ?? 0 }) : ''">{{ statsRead ? (stats.decided_disputes ?? stats.resolved_disputes) : '—' }}</div>
              <div class="drc-stat-card__label">{{ t('disputesView.stats.resolved') }}</div>
            </div>
          </div>
        </div>

        <div class="drc-stat-card">
          <div class="drc-stat-card__accent" style="background:var(--drc-cyan)"></div>
          <div class="drc-stat-card__body">
            <div class="drc-stat-card__icon" style="color:var(--drc-cyan)">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>
            </div>
            <div>
              <div class="drc-stat-card__value" style="color:var(--drc-cyan)">{{ statsRead && stats.resolution_rate !== null ? Math.round(stats.resolution_rate) + '%' : '—' }}</div>
              <div class="drc-stat-card__label">{{ t('disputesView.stats.rate') }}</div>
            </div>
          </div>
        </div>

        <div class="drc-stat-card">
          <div class="drc-stat-card__accent" style="background:var(--drc-purple)"></div>
          <div class="drc-stat-card__body">
            <div class="drc-stat-card__icon" style="color:var(--drc-purple)">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            </div>
            <div>
              <div class="drc-stat-card__value" data-testid="drc-avg-time"
                   :title="statsRead && stats.average_resolution_time === null ? t('disputesView.stats.avgNone', 'No dispute has a ruling with a date yet') : ''">{{ statsRead && stats.average_resolution_time !== null ? stats.average_resolution_time + 'h' : '—' }}</div>
              <div class="drc-stat-card__label">{{ t('disputesView.stats.avgTime') }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Command Bar -->
      <div class="drc-cmd-bar">
        <!-- Smart filter pills -->
        <div class="drc-pills">
          <button
            v-for="f in smartFilters" :key="f.id"
            :class="['drc-pill', activeSmartFilter === f.id && 'drc-pill--active']"
            @click="toggleSmartFilter(f)"
          >
            {{ f.label }}
            <span v-if="f.count > 0" class="drc-pill__badge">{{ f.count }}</span>
          </button>
        </div>

        <!-- Right controls -->
        <div class="drc-cmd-bar__right">
          <!-- Status filter -->
          <select v-model="statusFilter" class="drc-select" :aria-label="t('disputesView.statusFilterAria', 'Filter disputes by status')">
            <option value="all">{{ t('disputesView.status.all') }}</option>
            <option value="open">{{ t('disputesView.status.open') }}</option>
            <option value="investigating">{{ t('disputesView.status.investigating') }}</option>
            <option value="resolved">{{ t('disputesView.status.resolved') }}</option>
            <option value="dismissed">{{ t('disputesView.status.dismissed') }}</option>
          </select>

          <!-- Search -->
          <div class="drc-search-wrap">
            <svg class="drc-search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            <input v-model="searchQuery" class="drc-search" :placeholder="t('disputesView.searchPlaceholder')" :aria-label="t('disputesView.searchPlaceholder')" />
          </div>

          <!-- Export icon -->
          <button class="drc-icon-btn" :title="t('disputesView.export')" @click="exportToJSON">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          </button>

          <!-- Refresh -->
          <button class="drc-icon-btn" :class="{ 'drc-icon-btn--spin': loading }" :title="t('disputesView.refresh')" @click="refresh">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg>
          </button>

          <!-- File Dispute -->
          <button class="drc-file-btn" data-tour="dsp-file" @click="showFileModal = true">
            <svg class="drc-inline-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><line x1="12" y1="18" x2="12" y2="12"/><line x1="9" y1="15" x2="15" y2="15"/></svg>
            {{ t('disputesView.fileDispute') }}
          </button>
        </div>
      </div>

      <!-- Loading -->
      <div v-if="loading" class="drc-loader">
        <div class="drc-loader__ring"></div>
        <span>{{ t('disputesView.loading') }}</span>
      </div>

      <!-- Empty state — A4 (2026-05-08): added File First Dispute CTA when
           the all-disputes view is empty (only on the unfiltered case).
           Filter-empty case stays minimal so the user knows the issue is
           the filter, not lack of disputes. -->
      <!-- §FESUITE (the failing-reads census): with every read failed this said "No disputes filed yet" while the frame had
           disputes; nothing read is not none -->
      <ReadFailedNotice v-else-if="disputesStore.listFailed && !disputesStore.disputes.length" :retry="refresh" />
      <!-- "none" is an answer the list gives: with no agent known the page reads nothing (the census: the agents' read
           failed, the page never asked, and said "No disputes filed yet") -->
      <div v-else-if="disputesStore.listRead && filteredDisputes.length === 0" class="drc-empty">
        <svg class="drc-empty__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
        <p class="drc-empty__title">{{ statusFilter !== 'all' ? t('disputesView.empty.titleFiltered') : t('disputesView.empty.titleEmpty') }}</p>
        <p class="drc-empty__sub">
          <template v-if="statusFilter !== 'all'">{{ t('disputesView.empty.subFiltered') }}</template>
          <template v-else>{{ t('disputesView.empty.subEmpty') }}</template>
        </p>
        <button
          v-if="statusFilter === 'all'"
          class="drc-file-btn drc-empty__cta"
          @click="showFileModal = true"
        >
          {{ t('disputesView.fileFirstDispute') }}
        </button>
      </div>

      <!-- Dispute cards -->
      <div v-else class="drc-list">
        <!-- §COCKPITDESK (2026-10-15): the list is the registry's newest page; the tiles count them all -->
        <p v-if="statsRead && disputesStore.statusFilter === 'all' && !disputesStore.searchQuery && stats.total_disputes > shownDisputes.length"
           class="drc-list-note" data-testid="dsp-list-note">
          {{ tp('disputesView.list.newestOf', 'Showing the newest {n} of {total} disputes; the counts above cover them all.', { n: shownDisputes.length, total: stats.total_disputes + (stats.capped ? '+' : '') }) }}
        </p>
        <div
          v-for="dispute in shownDisputes"
          :key="dispute.id"
          class="drc-card"
          data-tour="dsp-card"
          :class="`drc-card--${dispute.status}`"
          @click="openDetail(dispute)"
        >
          <!-- Left accent bar is done via ::before in CSS via status class -->

          <!-- Card header -->
          <div class="drc-card__head">
            <div class="drc-card__head-left">
              <span class="drc-card__id">#{{ dispute.id }}</span>
              <span :class="['drc-status-pill', `drc-status-pill--${dispute.status}`]">{{ fmtStatus(dispute.status) }}</span>
              <span v-if="isPriority(dispute)" class="drc-priority-badge">{{ t('disputesView.highPriority') }}</span>
            </div>
            <div class="drc-card__date">
              <span>{{ fmtDate(dispute.created_at) }}</span>
              <span class="drc-card__ago">{{ timeAgo(dispute.created_at) }}</span>
            </div>
          </div>

          <!-- Description -->
          <p class="drc-card__desc">{{ truncate(dispute.description, 160) }}</p>

          <!-- Parties -->
          <div class="drc-card__parties">
            <div class="drc-party">
              <span class="drc-party__role">{{ t('disputesView.claimant') }}</span>
              <span class="drc-party__did">{{ shortDid(dispute.claimant_did) }}</span>
            </div>
            <div class="drc-party-sep">→</div>
            <div class="drc-party">
              <span class="drc-party__role">{{ t('disputesView.respondent') }}</span>
              <span class="drc-party__did">{{ shortDid(dispute.respondent_did) }}</span>
            </div>
          </div>

          <!-- Footer -->
          <div class="drc-card__foot">
            <span class="drc-card__evidence">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:13px;height:13px;display:inline"><path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/></svg>
              {{ dispute.evidence.length }} {{ t('disputesView.evidence') }}
            </span>
            <button class="drc-card__cta" @click.stop="openDetail(dispute)">{{ t('disputesView.viewDetails') }}</button>
          </div>
        </div>
        <!-- §COCKPITDESK (2026-10-15): twenty cards at a time (a hundred made a 21,000 px page) -->
        <button v-if="shownDisputes.length < filteredDisputes.length" type="button" class="drc-more" data-testid="dsp-show-more"
                @click="shownCount += SHOW_STEP">
          {{ tp('disputesView.list.showMore', 'Show {n} more', { n: Math.min(SHOW_STEP, filteredDisputes.length - shownDisputes.length) }) }}
        </button>
      </div>
    </div>

    <!-- ── File Dispute Modal ───────────────────────────────────────────────── -->
    <FileDisputeModal v-model="showFileModal" @filed="refresh" />

    <!-- ── Detail Modal ────────────────────────────────────────────────────── -->
    <Teleport to="body">
      <div v-if="showDetail && selectedDispute" class="drc-detail-overlay" @click.self="showDetail = false">
        <div class="drc-detail-modal" role="dialog" aria-modal="true" :aria-label="`${t('disputesView.detail.dispute')} #${selectedDispute.id}`">

          <!-- Header -->
          <div class="drc-detail-header">
            <div class="drc-detail-header__left">
              <span :class="['drc-status-pill', `drc-status-pill--${selectedDispute.status}`]">{{ fmtStatus(selectedDispute.status) }}</span>
              <span class="drc-detail-id">{{ t('disputesView.detail.dispute') }} #{{ selectedDispute.id }}</span>
            </div>
            <button type="button" class="drc-detail-close" :aria-label="t('common.close', 'Close')" @click="showDetail = false"><span aria-hidden="true">✕</span></button>
          </div>

          <!-- Tabs -->
          <div class="drc-detail-tabs" role="tablist">
            <button v-for="dtab in detailTabs" :key="dtab.id" type="button" role="tab" :data-tab="dtab.id" :aria-selected="detailTab === dtab.id" :class="['drc-detail-tab', detailTab === dtab.id && 'drc-detail-tab--active']" @click="detailTab = dtab.id">
              {{ dtab.label }}
              <span v-if="dtab.badge" class="drc-detail-tab__badge">{{ dtab.badge }}</span>
            </button>
          </div>

          <!-- Tab: Overview -->
          <div v-if="detailTab === 'overview'" class="drc-detail-body">
            <div class="drc-detail-section">
              <div class="drc-kv"><span class="drc-kv__k">{{ t('disputesView.detail.description') }}</span><span class="drc-kv__v">{{ selectedDispute.description }}</span></div>
            </div>
            <!-- DF1: contract context — link to source contract if dispute came from /contracts/malpractice -->
            <div v-if="(selectedDispute as any).contract_id" class="drc-detail-section">
              <div class="drc-kv">
                <span class="drc-kv__k">{{ t('disputesView.detail.sourceContract') }}</span>
                <span class="drc-kv__v">
                  <router-link
                    :to="{ path: '/contracts', hash: `#contract-${(selectedDispute as any).contract_id}` }"
                    style="color: var(--drc-cyan); text-decoration: underline;"
                  >
                    {{ t('contractsView.drawer.contract') }} #{{ (selectedDispute as any).contract_id }}{{ (selectedDispute as any).contract_name ? ' — ' + (selectedDispute as any).contract_name : '' }} →
                  </router-link>
                </span>
              </div>
            </div>
            <div class="drc-detail-section drc-detail-parties-grid">
              <div class="drc-detail-party-box">
                <div class="drc-detail-party-box__role">{{ t('disputesView.claimant') }}</div>
                <div class="drc-detail-party-box__did">{{ selectedDispute.claimant_did }}</div>
              </div>
              <div class="drc-detail-party-box">
                <div class="drc-detail-party-box__role">{{ t('disputesView.respondent') }}</div>
                <div class="drc-detail-party-box__did">{{ selectedDispute.respondent_did }}</div>
              </div>
            </div>
            <div class="drc-detail-section">
              <div class="drc-kv"><span class="drc-kv__k">{{ t('disputesView.detail.filed') }}</span><span class="drc-kv__v">{{ fmtDate(selectedDispute.created_at) }} ({{ timeAgo(selectedDispute.created_at) }})</span></div>
              <div class="drc-kv"><span class="drc-kv__k">{{ t('disputesView.detail.lastUpdated') }}</span><span class="drc-kv__v">{{ fmtDate(selectedDispute.updated_at) }}</span></div>
            </div>
          </div>

          <!-- Tab: Evidence -->
          <div v-else-if="detailTab === 'evidence'" class="drc-detail-body">
            <div v-if="selectedDispute.evidence.length === 0" class="drc-detail-empty">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="width:32px;height:32px;color:#8193ab"><path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/></svg>
              <p>{{ t('disputesView.evidenceTab.empty') }}</p>
              <button v-if="canSubmitEvidence(selectedDispute)" class="drc-btn drc-btn--primary" @click="openEvidence">{{ t('disputesView.evidenceTab.submitBtn') }}</button>
            </div>
            <div v-else class="drc-evidence-list">
              <div v-for="ev in selectedDispute.evidence" :key="ev.id" class="drc-ev-item">
                <div :class="['drc-ev-icon', `drc-ev-icon--${ev.type || 'text'}`]">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                </div>
                <div class="drc-ev-body">
                  <div class="drc-ev-meta">
                    <span class="drc-ev-who">{{ shortDid(ev.submitted_by) }}</span>
                    <span class="drc-ev-when">{{ fmtDate(ev.submitted_at) }}</span>
                  </div>
                  <p class="drc-ev-content">{{ ev.content }}</p>
                  <p v-if="ev.description && ev.description !== ev.content" class="drc-ev-sub">{{ ev.description }}</p>
                </div>
              </div>
            </div>
          </div>

          <!-- Tab: Timeline -->
          <div v-else-if="detailTab === 'timeline'" class="drc-detail-body">
            <DisputeTimeline :activities="buildTimeline(selectedDispute)" />
          </div>

          <!-- Tab: Ruling -->
          <div v-else-if="detailTab === 'ruling'" class="drc-detail-body">
            <div v-if="selectedDispute.ruling">
              <!-- Ruling banner -->
              <div class="drc-ruling-banner" :class="selectedDispute.status === 'resolved' ? 'drc-ruling-banner--resolved' : 'drc-ruling-banner--dismissed'">
                <div class="drc-ruling-banner__label">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:16px;height:16px"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                  {{ selectedDispute.status === 'resolved' ? t('disputesView.ruling.inFavour') : t('disputesView.ruling.dismissed') }}
                </div>
                <div class="drc-ruling-banner__date">{{ fmtDate(selectedDispute.updated_at) }}</div>
              </div>

              <!-- Compensation -->
              <div v-if="selectedDispute.compensation?.applied" class="drc-comp-box">
                <div class="drc-comp-box__header">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:15px;height:15px"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>
                  {{ t('disputesView.ruling.avtCompensation') }}
                  <span v-if="selectedDispute.compensation.partial" class="drc-comp-partial">{{ t('disputesView.ruling.partial') }}</span>
                </div>
                <div class="drc-comp-grid">
                  <div><div class="drc-kv__k">{{ t('disputesView.ruling.amount') }}</div><div class="drc-comp-amount">{{ selectedDispute.compensation.amount.toLocaleString(appLocale()) }} {{ localCurrency }}</div></div>
                  <div><div class="drc-kv__k">{{ t('disputesView.ruling.status') }}</div><div>{{ selectedDispute.compensation.partial ? `⚠ ${selectedDispute.compensation.deferred_amount} ${localCurrency}` : t('disputesView.ruling.fully') }}</div></div>
                  <div><div class="drc-kv__k">{{ t('disputesView.ruling.from') }}</div><div class="drc-kv__mono">{{ shortDid(selectedDispute.compensation.from_did || '') }}</div></div>
                  <div><div class="drc-kv__k">{{ t('disputesView.ruling.to') }}</div><div class="drc-kv__mono">{{ shortDid(selectedDispute.compensation.to_did || '') }}</div></div>
                </div>
                <div v-if="selectedDispute.compensation.transaction_id" class="drc-comp-tx">TX: {{ selectedDispute.compensation.transaction_id }}</div>
              </div>

              <!-- DF2: Cross-registry settlement progress -->
              <div
                v-if="(selectedDispute.compensation as any)?.cross_registry"
                class="drc-comp-box"
                style="border-color: rgba(var(--nc-primary-rgb), 0.4);"
              >
                <div class="drc-comp-box__header">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:15px;height:15px"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/></svg>
                  {{ t('disputesView.ruling.crossReg') }}
                </div>
                <div class="drc-comp-grid">
                  <div>
                    <div class="drc-kv__k">{{ t('disputesView.ruling.settlementStatus') }}</div>
                    <div>{{ (selectedDispute.compensation as any).settlement_status || '—' }}</div>
                  </div>
                  <div v-if="(selectedDispute.compensation as any).settlement_id">
                    <div class="drc-kv__k">{{ t('disputesView.ruling.settlementId') }}</div>
                    <div class="drc-kv__mono">{{ (selectedDispute.compensation as any).settlement_id }}</div>
                  </div>
                </div>
                <div style="margin-top: 0.75rem;">
                  <router-link
                    :to="'/settlements'"
                    style="color: var(--drc-cyan); text-decoration: underline; font-size: 0.85rem;"
                  >
                    {{ t('disputesView.ruling.viewSettlements') }}
                  </router-link>
                </div>
              </div>

              <!-- Reputation -->
              <div v-if="selectedDispute.reputation_changes" class="drc-rep-box">
                <div class="drc-rep-box__header">{{ t('disputesView.ruling.reputation') }}</div>
                <div class="drc-rep-grid">
                  <div>
                    <div class="drc-kv__k">{{ t('disputesView.claimant') }}</div>
                    <div :class="['drc-rep-delta', (selectedDispute.reputation_changes.complainant?.change || 0) >= 0 ? 'drc-rep-delta--pos' : 'drc-rep-delta--neg']">
                      {{ (selectedDispute.reputation_changes.complainant?.change || 0) >= 0 ? '+' : '' }}{{ selectedDispute.reputation_changes.complainant?.change ?? '—' }}
                      <span class="drc-rep-range">({{ selectedDispute.reputation_changes.complainant?.initial }} → {{ selectedDispute.reputation_changes.complainant?.final }})</span>
                    </div>
                  </div>
                  <div>
                    <div class="drc-kv__k">{{ t('disputesView.respondent') }}</div>
                    <div :class="['drc-rep-delta', (selectedDispute.reputation_changes.defendant?.change || 0) >= 0 ? 'drc-rep-delta--pos' : 'drc-rep-delta--neg']">
                      {{ (selectedDispute.reputation_changes.defendant?.change || 0) >= 0 ? '+' : '' }}{{ selectedDispute.reputation_changes.defendant?.change ?? '—' }}
                      <span class="drc-rep-range">({{ selectedDispute.reputation_changes.defendant?.initial }} → {{ selectedDispute.reputation_changes.defendant?.final }})</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- No ruling yet -->
            <div v-else class="drc-detail-empty">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="width:32px;height:32px;color:#8193ab"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
              <p>{{ t('disputesView.ruling.noRuling') }}</p>
              <button
                v-if="isAdmin && ['open','investigating'].includes(selectedDispute.status)"
                class="drc-btn drc-btn--success"
                @click="openRuling"
              >{{ t('disputesView.ruling.makeRuling') }}</button>
            </div>
          </div>

          <!-- Detail footer -->
          <div class="drc-detail-footer">
            <div class="drc-detail-footer__left">
              <button v-if="canSubmitEvidence(selectedDispute)" class="drc-btn drc-btn--primary" @click="openEvidence">{{ t('disputesView.evidenceTab.submitBtn') }}</button>
            </div>
            <div class="drc-detail-footer__right">
              <button v-if="isAdmin && ['open','investigating'].includes(selectedDispute.status)" class="drc-btn drc-btn--success" @click="openRuling">{{ t('disputesView.ruling.makeRuling') }}</button>
              <button class="drc-btn drc-btn--ghost" @click="showDetail = false">{{ t('disputesView.footer.close') }}</button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ── Submit Evidence Modal ───────────────────────────────────────────── -->
    <Teleport to="body">
      <div v-if="showEvidenceModal" class="tp-overlay" @click.self="showEvidenceModal = false">
        <div class="tp-modal" role="dialog" aria-modal="true" aria-labelledby="dsp-ev-title">
          <div class="tp-modal-header">
            <span id="dsp-ev-title" class="tp-modal-title">{{ t('disputesView.evidenceModal.title') }}</span>
            <button type="button" class="tp-modal-close" :aria-label="t('common.close', 'Close')" @click="showEvidenceModal = false"><span aria-hidden="true">✕</span></button>
          </div>
          <div class="tp-modal-body">
            <div class="tp-field">
              <label class="tp-label" for="dsp-ev-type">{{ t('disputesView.evidenceModal.type') }}</label>
              <select id="dsp-ev-type" v-model="evidenceForm.type" class="tp-select">
                <option value="text">{{ t('disputesView.evidenceModal.typeText') }}</option>
                <option value="link">{{ t('disputesView.evidenceModal.typeLink') }}</option>
                <option value="document">{{ t('disputesView.evidenceModal.typeDoc') }}</option>
              </select>
            </div>
            <div class="tp-field">
              <label class="tp-label" for="dsp-ev-content">{{ t('disputesView.evidenceModal.content') }} <span style="color:#ef4444">*</span></label>
              <textarea id="dsp-ev-content" v-model="evidenceForm.content" class="tp-textarea" rows="4" :placeholder="t('disputesView.evidenceModal.contentPh')"></textarea>
            </div>
            <div class="tp-field">
              <label class="tp-label" for="dsp-ev-desc">{{ t('disputesView.evidenceModal.descLabel') }}</label>
              <input id="dsp-ev-desc" v-model="evidenceForm.description" class="tp-input" :placeholder="t('disputesView.evidenceModal.descPh')" />
            </div>
          </div>
          <div class="tp-modal-footer">
            <button class="tp-btn tp-btn--ghost" @click="showEvidenceModal = false">{{ t('disputesView.evidenceModal.cancel') }}</button>
            <button class="tp-btn tp-btn--primary" :disabled="!evidenceForm.content || submittingEvidence" @click="submitEvidence">
              <span v-if="submittingEvidence"><span class="tp-spinner"></span> {{ t('disputesView.evidenceModal.submitting') }}</span>
              <span v-else>{{ t('disputesView.evidenceModal.submit') }}</span>
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ── Make Ruling Modal ───────────────────────────────────────────────── -->
    <Teleport to="body">
      <div v-if="showRulingModal" class="tp-overlay" @click.self="showRulingModal = false">
        <div class="tp-modal">
          <div class="tp-modal-header">
            <span class="tp-modal-title">{{ t('disputesView.rulingModal.title') }} #{{ selectedDispute?.id }}</span>
            <button class="tp-modal-close" @click="showRulingModal = false">✕</button>
          </div>
          <div class="tp-modal-body">
            <div class="tp-field">
              <label class="tp-label">{{ t('disputesView.rulingModal.resolution') }} <span style="color:#ef4444">*</span></label>
              <select v-model="rulingForm.resolution" class="tp-select">
                <option value="">{{ t('disputesView.rulingModal.resolutionPlaceholder') }}</option>
                <option value="resolved">{{ t('disputesView.rulingModal.resolutionResolved') }}</option>
                <option value="dismissed">{{ t('disputesView.rulingModal.resolutionDismissed') }}</option>
              </select>
            </div>
            <div class="tp-field">
              <label class="tp-label">{{ t('disputesView.rulingModal.notes') }} <span style="color:#ef4444">*</span></label>
              <textarea v-model="rulingForm.notes" class="tp-textarea" rows="5" :placeholder="t('disputesView.rulingModal.notesPh')" style="min-height:120px"></textarea>
            </div>
            <div class="tp-banner tp-banner--warn">
              {{ t('disputesView.rulingModal.warnA') }}
              {{ rulingForm.resolution === 'resolved' ? ' ' + t('disputesView.rulingModal.warnB') + ' ' : ' ' }}
              {{ t('disputesView.rulingModal.warnC') }}
            </div>
          </div>
          <div class="tp-modal-footer">
            <button class="tp-btn tp-btn--ghost" @click="showRulingModal = false">{{ t('disputesView.rulingModal.cancel') }}</button>
            <button class="tp-btn tp-btn--success" :disabled="!rulingForm.resolution || !rulingForm.notes || submittingRuling" @click="submitRuling">
              <span v-if="submittingRuling"><span class="tp-spinner"></span> {{ t('disputesView.rulingModal.applying') }}</span>
              <span v-else>{{ t('disputesView.rulingModal.submit') }}</span>
            </button>
          </div>
        </div>
      </div>
    </Teleport>

  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import { useDisputesStore } from '@/stores/disputes'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
import { useI18n } from '@/composables/useI18n'
import type { Dispute } from '@/services/api/disputes'
import DisputeTimeline from '@/components/DisputeTimeline.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import DisputeAnalytics from '@/components/DisputeAnalytics.vue'
import FileDisputeModal from '@/components/disputes/FileDisputeModal.vue'
import { useEscapeClose } from '@/composables/useEscapeClose'
import '@/components/disputes/tp-disputes-modals.css'

dayjs.extend(relativeTime)

const { t, tp } = useI18n()
import { useCurrency } from '@/composables/useCurrency'
const { localCurrency } = useCurrency()

const disputesStore = useDisputesStore()
const authStore    = useAuthStore()
const uiStore      = useUIStore()

// ── State ──────────────────────────────────────────────────────────────────
const activeTab        = ref<'disputes' | 'analytics'>('disputes')
const activeSmartFilter = ref<string | null>(null)
const showFileModal    = ref(false)
const showDetail       = ref(false)
const showEvidenceModal = ref(false)
const showRulingModal  = ref(false)
const selectedDispute  = ref<Dispute | null>(null)
// Escape closes the topmost of the two overlays wherever the focus is (useEscapeClose; their @keydown.esc never heard it)
useEscapeClose(() => showDetail.value && !!selectedDispute.value, () => { showDetail.value = false })
useEscapeClose(showEvidenceModal, () => { showEvidenceModal.value = false })
const detailTab        = ref('overview')
const submittingEvidence = ref(false)
const submittingRuling   = ref(false)

const evidenceForm = ref({ type: 'text' as const, content: '', description: '' })
const rulingForm   = ref({ resolution: '' as '' | 'resolved' | 'dismissed', notes: '' })

// ── Computed ───────────────────────────────────────────────────────────────
const loading          = computed(() => disputesStore.loading)
const filteredDisputes = computed(() => disputesStore.filteredDisputes)
const SHOW_STEP = 20
const shownCount = ref(SHOW_STEP)
const shownDisputes = computed(() => filteredDisputes.value.slice(0, shownCount.value))
// a new filter or search starts at the top again
watch(() => [disputesStore.statusFilter, disputesStore.searchQuery], () => { shownCount.value = SHOW_STEP })
const stats            = computed(() => disputesStore.stats)
const statsRead        = computed(() => disputesStore.statsRead)
const myDid            = computed(() => authStore.activeAgent?.did || authStore.activeAgent?.agent_did || '')
// OWL-17 FIX-D07: use is_admin not role
const isAdmin          = computed(() => (authStore.user as any)?.is_admin === true)

const statusFilter = computed({
  get: () => disputesStore.statusFilter,
  set: (v) => disputesStore.setStatusFilter(v)
})
const searchQuery = computed({
  get: () => disputesStore.searchQuery,
  set: (v) => disputesStore.setSearchQuery(v)
})

const detailTabs = computed(() => [
  { id: 'overview',  label: t('disputesView.detail.tabs.overview') },
  { id: 'evidence',  label: t('disputesView.detail.tabs.evidence'), badge: selectedDispute.value?.evidence.length || 0 },
  { id: 'timeline',  label: t('disputesView.detail.tabs.timeline') },
  { id: 'ruling',    label: t('disputesView.detail.tabs.ruling') }
])

const smartFilters = computed(() => {
  const all = disputesStore.disputes
  return [
    {
      id: 'my-disputes',
      label: t('disputesView.smartFilters.mine'),
      count: all.filter(d => d.claimant_did === myDid.value || d.respondent_did === myDid.value).length,
      apply: () => {
        disputesStore.setStatusFilter('all')
        // filter by DID client-side via search
        disputesStore.setSearchQuery(myDid.value)
      }
    },
    {
      id: 'open',
      label: t('disputesView.smartFilters.open'),
      count: all.filter(d => d.status === 'open').length,
      apply: () => { disputesStore.setStatusFilter('open'); disputesStore.setSearchQuery('') }
    },
    {
      id: 'high-priority',
      label: t('disputesView.smartFilters.highPriority'),
      count: all.filter(d => isPriority(d)).length,
      apply: () => {
        disputesStore.setStatusFilter('open')
        disputesStore.setSearchQuery('')
      }
    },
    {
      id: 'resolved',
      label: t('disputesView.smartFilters.resolved'),
      count: all.filter(d => d.status === 'resolved').length,
      apply: () => { disputesStore.setStatusFilter('resolved'); disputesStore.setSearchQuery('') }
    }
  ]
})

// ── Methods ────────────────────────────────────────────────────────────────
async function refresh() {
  try {
    await disputesStore.fetchDisputes()
  } catch (e: any) {
    uiStore.showError(t('disputesView.error.loadFailed'), t('disputesView.error.loadFailedMsg'))
  }
}

function toggleSmartFilter(f: any) {
  if (activeSmartFilter.value === f.id) {
    activeSmartFilter.value = null
    disputesStore.clearFilters()
  } else {
    activeSmartFilter.value = f.id
    f.apply()
  }
}

function openDetail(dispute: Dispute) {
  selectedDispute.value = dispute
  detailTab.value = 'overview'
  showDetail.value = true
}

function openEvidence() {
  evidenceForm.value = { type: 'text', content: '', description: '' }
  showEvidenceModal.value = true
}

function openRuling() {
  rulingForm.value = { resolution: '', notes: '' }
  showRulingModal.value = true
}

async function submitEvidence() {
  if (!selectedDispute.value || !evidenceForm.value.content) return
  submittingEvidence.value = true
  try {
    await disputesStore.submitEvidence(selectedDispute.value.id, {
      type: evidenceForm.value.type,
      content: evidenceForm.value.content,
      description: evidenceForm.value.description || undefined
    })
    showEvidenceModal.value = false
    // Refresh the dispute in the list
    const updated = await disputesStore.fetchDispute(selectedDispute.value.id)
    if (updated) selectedDispute.value = updated
  } catch (e: any) {
    uiStore.showError(t('disputesView.error.evidenceFailed'), e.message || t('disputesView.error.evidenceFailedMsg'))
  } finally {
    submittingEvidence.value = false
  }
}

async function submitRuling() {
  if (!selectedDispute.value || !rulingForm.value.resolution || !rulingForm.value.notes) return
  submittingRuling.value = true
  try {
    const result = await disputesStore.updateRuling(
      selectedDispute.value.id,
      rulingForm.value.notes,
      rulingForm.value.resolution
    )
    showRulingModal.value = false
    if (result?.dispute) {
      selectedDispute.value = result.dispute
      detailTab.value = 'ruling'
    }
  } catch (e: any) {
    uiStore.showError(t('disputesView.error.rulingFailed'), e.message || t('disputesView.error.rulingFailedMsg'))
  } finally {
    submittingRuling.value = false
  }
}

function canSubmitEvidence(d: Dispute) {
  if (d.status === 'resolved' || d.status === 'dismissed') return false
  return d.claimant_did === myDid.value || d.respondent_did === myDid.value
}

function isPriority(d: Dispute) {
  const age = dayjs().diff(dayjs(d.created_at), 'day')
  return age > 7 || d.evidence.length > 3 || d.status === 'investigating'
}

function buildTimeline(d: Dispute) {
  const items: any[] = [{
    id: 'created',
    type: 'created',
    title: t('disputesView.timeline.disputeFiled'),
    description: d.reason,
    timestamp: d.created_at,
    metadata: { submitted_by: shortDid(d.claimant_did) }
  }]
  d.evidence.forEach((ev, i) => {
    items.push({
      id: `ev-${i}`,
      type: 'evidence_submitted',
      title: t('disputesView.timeline.evidenceSubmitted'),
      description: ev.content.substring(0, 100),
      timestamp: ev.submitted_at,
      metadata: { evidence_type: ev.type, submitted_by: shortDid(ev.submitted_by) }
    })
  })
  if (d.ruling) {
    items.push({
      id: 'ruling',
      type: 'ruling_made',
      title: t('disputesView.timeline.rulingMade'),
      description: d.status === 'resolved' ? t('disputesView.timeline.inFavour') : t('disputesView.timeline.dismissed'),
      timestamp: d.updated_at,
      metadata: { ruling_type: d.status }
    })
  }
  return items.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
}

function exportToJSON() {
  const json = JSON.stringify(filteredDisputes.value, null, 2)
  const blob = new Blob([json], { type: 'application/json' })
  const url  = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = 'disputes.json'; a.click()
  URL.revokeObjectURL(url)
}

// ── Formatters ─────────────────────────────────────────────────────────────
function fmtDate(d: string)   { return dayjs(d).format('MMM D, YYYY') }
function timeAgo(d: string)   { return dayjs(d).fromNow() }
function fmtStatus(s: string) { return s.charAt(0).toUpperCase() + s.slice(1) }
function truncate(s: string, n: number) { return s.length > n ? s.slice(0, n) + '…' : s }
function shortDid(did: string) {
  if (!did) return t('disputesView.claimantUnknown')
  const core = did.replace('did:cos:', '')
  return core.length > 16 ? core.slice(0, 8) + '…' + core.slice(-4) : core
}

// ── Lifecycle ──────────────────────────────────────────────────────────────
// an agent known only after the page opened (its list read late, or a pick): read its disputes then
watch(() => authStore.activeAgent?.did || (authStore.activeAgent as any)?.agent_did, (did, prev) => {
  if (did && did !== prev) void refresh()
})

onMounted(async () => {
  if (!authStore.activeAgent?.did && !(authStore.activeAgent as any)?.agent_did) return
  await refresh()

  // X3 fix: auto-open drawer if URL hash specifies a dispute (e.g., from
  // contract malpractice redirect: /disputes#dispute-N)
  try {
    const hash = window.location.hash || ''
    const m = hash.match(/^#dispute-(\d+)/)
    if (m) {
      const id = parseInt(m[1], 10)
      const found = disputesStore.disputes.find((d: any) => d.id === id)
      if (found) openDetail(found)
    }
  } catch (e) {
    // non-fatal
  }
})

const timer = setInterval(refresh, 30_000)
onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
/* ── Theme tokens (mirrors AdminCanaries Phase 11 polish, 2026-05-06) ─────
   Brand-mapped accent so 'neural'/'sovereign' theme switches propagate.
   Semantic status colors stay fixed across themes.
*/
/* §FESUITE — the detail and evidence dialogs are teleported to <body>, outside .drc-view: without the tokens there
   the detail's primary button painted dark text on no background (1.1:1, "Submit Evidence" unreadable). */
.drc-view, .drc-detail-overlay {
  --drc-cyan:    var(--nc-primary, rgb(0, 210, 210));
  --drc-cyan-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --drc-red:     var(--nc-danger,  rgb(239, 68, 68));
  --drc-orange:  var(--nc-warning, rgb(249, 115, 22));
  --drc-green:   var(--nc-success, rgb(34, 197, 94));
  --drc-purple:  rgb(167, 139, 250);
  --drc-mono:    'IBM Plex Mono', 'Fira Code', monospace;

  --drc-surface: var(--nc-surface, #111827);
  --drc-surface-2: var(--nc-deep, #0a0d16);
  --drc-border:  var(--nc-border, rgba(var(--drc-cyan-rgb), 0.18));
  --drc-text-bright: var(--nc-text-primary, #e8eaed);
  --drc-text-muted:  var(--nc-text-muted, #6b7785);
}
.drc-view {
  position: relative;
  min-height: 100vh;
  padding: 0 0 32px 0;
  /* §pass50.4 — opaque background removed; DashboardLayout's <ViewAmbient> paints. */
  color: var(--drc-text-bright);
  transition: color 240ms ease;
  z-index: 1;
}

/* ── Ambient background ─────────────────────────────────────────────────── */
.drc-ambient {
  position: fixed; inset: 0; z-index: 0; pointer-events: none; overflow: hidden;
}
.drc-grid {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(var(--drc-cyan-rgb), 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--drc-cyan-rgb), 0.03) 1px, transparent 1px);
  background-size: 60px 60px;
  /* §DESKCHROME 2026-08-28: grid is STATIC — perpetual drift removed (Commander) */
}
.drc-scan {
  position: absolute; inset: 0;
  background: repeating-linear-gradient(
    180deg,
    transparent 0, transparent 3px,
    rgba(var(--drc-cyan-rgb), 0.025) 3px, rgba(var(--drc-cyan-rgb), 0.025) 4px
  );
}
.drc-glow {
  position: absolute; border-radius: 50%; filter: blur(120px); opacity: 0.18;
}
.drc-glow-1 { width: 480px; height: 480px; background: rgba(var(--drc-cyan-rgb), 0.6); top: -100px; right: -100px; }
.drc-glow-2 { width: 360px; height: 360px; background: rgba(239, 68, 68, 0.4); bottom: -80px; left: -80px; }

/* ── Hero strip ─────────────────────────────────────────────────────────── */
.drc-hero {
  position: relative; z-index: 1;
  padding: 48px 32px 24px;
}
.drc-hero-inner { max-width: 1400px; margin: 0 auto; }
.drc-chip-hero {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--drc-mono); font-size: 10px; font-weight: 600;
  letter-spacing: 0.18em; color: var(--drc-cyan);
  padding: 4px 12px;
  border: 1px solid rgba(var(--drc-cyan-rgb), 0.25);
  border-radius: 99px; margin-bottom: 14px;
  background: rgba(var(--drc-cyan-rgb), 0.04);
}
.drc-chip-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--drc-cyan);
  box-shadow: 0 0 8px var(--drc-cyan);
  animation: drcPulse 1.6s ease-in-out infinite;
}
@keyframes drcPulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
.drc-h1 {
  font-family: 'Orbitron', 'IBM Plex Sans', sans-serif;
  font-weight: 800; font-size: 34px; letter-spacing: 0.02em;
  margin: 0 0 10px; color: var(--drc-text-bright); line-height: 1.15;
}
.drc-accent { color: var(--drc-cyan); text-shadow: 0 0 14px rgba(var(--drc-cyan-rgb), 0.45); }
.drc-lead { color: var(--drc-text-muted); font-size: 14px; max-width: 760px; line-height: 1.7; margin: 0; }

/* All inner sections render above the ambient layer */
.drc-header, .drc-stats, .drc-cmd, .drc-list, .drc-card, .drc-detail-overlay {
  position: relative; z-index: 1;
}
.drc-header, .drc-stats, .drc-cmd, .drc-cmd-bar, .drc-list {
  max-width: 1400px;
  margin-left: auto;
  margin-right: auto;
  padding-left: 32px;
  padding-right: 32px;
}

/* ── Header ────────────────────────────────────────────────────────────── */
.drc-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 2rem;
  gap: 1rem;
}
.drc-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 1.6rem;
  font-weight: 700;
  color: var(--drc-cyan);
  letter-spacing: -0.02em;
}
.drc-subtitle {
  font-size: 0.8rem;
  color: #8193ab;
  margin-top: 0.3rem;
  letter-spacing: 0.04em;
}
.drc-tabs {
  display: flex;
  gap: 2px;
  background: rgba(0,0,0,0.3);
  border: 1px solid var(--drc-border);
  border-radius: 8px;
  padding: 3px;
}
.drc-tab {
  padding: 0.4rem 1.1rem;
  border-radius: 6px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #8a9bb0;
  background: transparent;
  border: none;
  cursor: pointer;
  transition: all 0.15s;
}
.drc-tab--active {
  background: rgba(var(--nc-primary-rgb),0.12);
  color: var(--drc-cyan);
}

/* ── Stat cards ────────────────────────────────────────────────────────── */
.drc-stats {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 1rem;
  margin-bottom: 1.5rem;
}
@media (max-width: 1100px) { .drc-stats { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 640px)  { .drc-stats { grid-template-columns: repeat(2, 1fr); } }

.drc-stat-card {
  background: var(--drc-surface);
  border: 1px solid var(--drc-border);
  border-radius: 10px;
  overflow: hidden;
  position: relative;
}
.drc-stat-card__accent {
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 3px;
}
.drc-stat-card__body {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem 1rem 1rem 1.25rem;
}
.drc-stat-card__icon { flex-shrink: 0; }
.drc-stat-card__icon svg { width: 28px; height: 28px; }
.drc-stat-card__value {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 1.6rem;
  font-weight: 700;
  color: #e2e8f0;
  line-height: 1;
}
.drc-stat-card__label {
  font-size: 0.72rem;
  color: #8193ab;
  margin-top: 0.25rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

/* ── Command bar ───────────────────────────────────────────────────────── */
.drc-cmd-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1.25rem;
  flex-wrap: wrap;
}
.drc-pills { display: flex; gap: 0.5rem; flex-wrap: wrap; }
.drc-pill {
  display: flex; align-items: center; gap: 0.3rem;
  padding: 0.35rem 0.9rem;
  border-radius: 9999px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem; font-weight: 600;
  letter-spacing: 0.07em; text-transform: uppercase;
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--drc-border);
  color: #8a9bb0;
  cursor: pointer; transition: all 0.15s;
}
.drc-pill:hover  { background: rgba(var(--nc-primary-rgb),0.08); color: var(--drc-cyan); }
.drc-pill--active { background: rgba(var(--nc-primary-rgb),0.15); color: var(--drc-cyan); border-color: rgba(var(--nc-primary-rgb),0.4); }
.drc-pill__badge {
  background: rgba(var(--nc-primary-rgb),0.2);
  color: var(--drc-cyan);
  border-radius: 9999px;
  padding: 0 0.4rem;
  font-size: 0.65rem;
  min-width: 18px; text-align: center;
}

.drc-cmd-bar__right { display: flex; align-items: center; gap: 0.5rem; }

/* Harmonized 34px control height across the command bar so select / search /
   icon buttons / file-btn share the same baseline (was: icon-btn=34px while
   select/search/file-btn rendered ~32px due to intrinsic font + padding). */
.drc-select,
.drc-search,
.drc-icon-btn,
.drc-file-btn {
  height: 34px;
  box-sizing: border-box;
  line-height: 1;
}

.drc-select {
  background: var(--drc-surface);
  border: 1px solid var(--drc-border);
  border-radius: 7px;
  color: #c8d6e8;
  padding: 0 0.85rem;
  font-size: 0.82rem;
  outline: none;
  cursor: pointer;
}

.drc-search-wrap { position: relative; display: flex; align-items: center; }
.drc-search-icon {
  position: absolute; left: 0.7rem; top: 50%; transform: translateY(-50%);
  width: 14px; height: 14px; color: #8193ab; pointer-events: none;
}
.drc-search {
  background: var(--drc-surface);
  border: 1px solid var(--drc-border);
  border-radius: 7px;
  color: #c8d6e8;
  padding: 0 0.85rem 0 2.1rem;
  font-size: 0.82rem;
  outline: none;
  width: 220px;
}
.drc-search:focus { border-color: rgba(var(--nc-primary-rgb),0.45); }
.drc-search::placeholder { color: #4a5568; }

.drc-icon-btn {
  width: 34px;
  border-radius: 7px;
  background: var(--drc-surface);
  border: 1px solid var(--drc-border);
  color: #8a9bb0;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  padding: 0;
  transition: all 0.15s;
}
.drc-icon-btn svg { width: 15px; height: 15px; }
.drc-icon-btn:hover { background: rgba(var(--nc-primary-rgb),0.08); color: var(--drc-cyan); }
.drc-icon-btn--spin svg { animation: drc-spin 0.8s linear infinite; }

.drc-file-btn {
  padding: 0 1.1rem;
  border-radius: 7px;
  background: var(--drc-cyan);
  color: #060b14;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem; font-weight: 700;
  letter-spacing: 0.08em; text-transform: uppercase;
  border: none; cursor: pointer;
  display: inline-flex; align-items: center; gap: .45rem; /* §COCKPITDESK (2026-10-15): the icon touched its label */
  transition: background 0.15s;
}
.drc-file-btn:hover { background: rgba(var(--nc-primary-rgb),0.85); }

/* ── Loader / empty ────────────────────────────────────────────────────── */
.drc-loader {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 1rem; padding: 4rem;
  color: #8193ab; font-size: 0.85rem;
}
.drc-loader__ring {
  width: 40px; height: 40px;
  border: 3px solid rgba(var(--nc-primary-rgb),0.15);
  border-top-color: var(--drc-cyan);
  border-radius: 50%;
  animation: drc-spin 0.8s linear infinite;
}
.drc-empty {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 0.75rem; padding: 4rem; color: #8193ab; text-align: center;
}
.drc-empty__icon { width: 48px; height: 48px; }
.drc-empty__title { font-size: 1rem; font-weight: 600; color: #8a9bb0; }
.drc-empty__sub { font-size: 0.82rem; max-width: 460px; line-height: 1.55; }
.drc-empty__cta { margin-top: 1rem; }

/* ── Dispute cards ─────────────────────────────────────────────────────── */
.drc-list { display: flex; flex-direction: column; gap: 0.75rem; }
.drc-list-note { margin: 0; font-size: 0.75rem; color: var(--nc-text-muted, #8f9399); }
.drc-more { align-self: center; margin-top: .25rem; padding: .55rem 1.1rem; background: transparent; border: 1px solid rgba(var(--nc-primary-rgb), .35);
  border-radius: 8px; color: var(--nc-primary, #00e5ff); font-size: .8rem; letter-spacing: .04em; cursor: pointer; }
.drc-more:hover { background: rgba(var(--nc-primary-rgb), .08); }

.drc-card {
  background: var(--drc-surface);
  border: 1px solid var(--drc-border);
  border-radius: 10px;
  padding: 1.1rem 1.25rem;
  cursor: pointer;
  position: relative;
  transition: box-shadow 0.2s, border-color 0.2s;
  border-left: 3px solid transparent;
}
.drc-card:hover {
  box-shadow: 0 0 18px rgba(var(--nc-primary-rgb),0.07);
  border-color: rgba(var(--nc-primary-rgb),0.25);
}
.drc-card--open        { border-left-color: var(--drc-red); }
.drc-card--investigating { border-left-color: #f59e0b; }
.drc-card--resolved    { border-left-color: var(--drc-green); }
.drc-card--dismissed   { border-left-color: #6b7280; }

.drc-card__head {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 0.6rem;
}
.drc-card__head-left { display: flex; align-items: center; gap: 0.6rem; }
.drc-card__id {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem; color: #8193ab;
}
.drc-card__date {
  display: flex; flex-direction: column; align-items: flex-end;
  font-size: 0.75rem; color: #8a9bb0;
}
.drc-card__ago { font-size: 0.7rem; color: #4a5568; }

/* Status pills */
.drc-status-pill {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem; font-weight: 600;
  letter-spacing: 0.08em; text-transform: uppercase;
  padding: 0.2rem 0.6rem; border-radius: 9999px;
}
.drc-status-pill--open        { background: rgba(239,68,68,0.12); color: var(--drc-red); }
.drc-status-pill--investigating { background: rgba(245,158,11,0.12); color: #f59e0b; }
.drc-status-pill--resolved    { background: rgba(34,197,94,0.12); color: var(--drc-green); }
.drc-status-pill--dismissed   { background: rgba(107,114,128,0.15); color: #9ca3af; }

.drc-priority-badge {
  font-size: 0.65rem; font-weight: 600;
  padding: 0.2rem 0.55rem; border-radius: 9999px;
  background: rgba(239,68,68,0.1);
  color: var(--drc-red);
  border: 1px solid rgba(239,68,68,0.25);
  text-transform: uppercase; letter-spacing: 0.06em;
}

.drc-card__desc {
  font-size: 0.85rem; color: #8fa3be;
  line-height: 1.5; margin-bottom: 0.75rem;
}

.drc-card__parties {
  display: flex; align-items: center; gap: 0.75rem;
  margin-bottom: 0.75rem;
}
.drc-party { display: flex; flex-direction: column; gap: 0.15rem; }
.drc-party__role {
  font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.08em; color: #8193ab;
}
.drc-party__did {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.73rem; color: #c8d6e8;
}
.drc-party-sep { color: #8193ab; font-size: 0.9rem; }

.drc-card__foot {
  display: flex; align-items: center; justify-content: space-between;
  padding-top: 0.65rem;
  border-top: 1px solid rgba(var(--nc-primary-rgb),0.07);
}
.drc-card__evidence { display: flex; align-items: center; gap: 0.35rem; font-size: 0.75rem; color: #8193ab; }
.drc-card__cta { font-size: 0.8rem; color: var(--drc-cyan); font-weight: 600; background: none; border: none; cursor: pointer; }
.drc-card__cta:hover { opacity: 0.75; }

/* ── Detail modal ──────────────────────────────────────────────────────── */
.drc-detail-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.72); backdrop-filter: blur(4px);
  display: flex; align-items: center; justify-content: center;
  z-index: 9800;
  animation: tp-fade-in 0.15s ease;
}
.drc-detail-modal {
  background: #0d1626;
  border: 1px solid rgba(var(--nc-primary-rgb),0.2);
  border-radius: 12px;
  width: min(96vw, 720px);
  max-height: 90vh;
  display: flex; flex-direction: column;
  box-shadow: 0 20px 60px rgba(0,0,0,0.6);
  animation: tp-entry 0.18s cubic-bezier(0.4,0,0.2,1);
}
.drc-detail-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 1.1rem 1.5rem;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.1);
  flex-shrink: 0;
}
.drc-detail-header__left { display: flex; align-items: center; gap: 0.75rem; }
.drc-detail-id {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.8rem; color: #8a9bb0;
}
.drc-detail-close {
  width: 28px; height: 28px; border-radius: 6px;
  border: 1px solid rgba(var(--nc-primary-rgb),0.15);
  background: transparent; color: #8fa3be;
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  font-size: 1rem; transition: all 0.15s;
}
.drc-detail-close:hover { background: rgba(var(--nc-primary-rgb),0.08); color: var(--drc-cyan); }

.drc-detail-tabs {
  display: flex; gap: 0;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.1);
  padding: 0 1.5rem;
  flex-shrink: 0;
}
.drc-detail-tab {
  padding: 0.7rem 1.1rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem; font-weight: 600;
  letter-spacing: 0.07em; text-transform: uppercase;
  color: #8193ab; border-bottom: 2px solid transparent;
  background: none; border-top: none; border-left: none; border-right: none;
  cursor: pointer; transition: all 0.15s;
}
.drc-detail-tab:hover { color: #8fa3be; }
.drc-detail-tab--active { color: var(--drc-cyan); border-bottom-color: var(--drc-cyan); }
.drc-detail-tab__badge {
  margin-left: 0.35rem; padding: 0.1rem 0.45rem;
  background: rgba(var(--nc-primary-rgb),0.12); color: var(--drc-cyan);
  border-radius: 9999px; font-size: 0.62rem;
}

.drc-detail-body {
  flex: 1; overflow-y: auto;
  padding: 1.25rem 1.5rem;
  display: flex; flex-direction: column; gap: 1rem;
}
.drc-detail-section {
  background: rgba(255,255,255,0.02);
  border: 1px solid rgba(var(--nc-primary-rgb),0.07);
  border-radius: 8px; padding: 0.85rem 1rem;
}
.drc-kv { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; padding: 0.35rem 0; border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.06); }
.drc-kv:last-child { border-bottom: none; }
.drc-kv__k { font-family: 'IBM Plex Mono', monospace; font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.08em; color: #8193ab; flex-shrink: 0; padding-top: 2px; }
.drc-kv__v { color: #c8d6e8; font-size: 0.85rem; text-align: right; }
.drc-kv__mono { font-family: 'IBM Plex Mono', monospace; font-size: 0.73rem; color: #8fa3be; }

.drc-detail-parties-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; border: none; padding: 0; background: none; }
.drc-detail-party-box {
  background: rgba(255,255,255,0.02); border: 1px solid rgba(var(--nc-primary-rgb),0.07);
  border-radius: 8px; padding: 0.85rem 1rem;
}
.drc-detail-party-box__role { font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.1em; color: #8193ab; margin-bottom: 0.4rem; }
.drc-detail-party-box__did { font-family: 'IBM Plex Mono', monospace; font-size: 0.73rem; color: #c8d6e8; word-break: break-all; }

.drc-detail-empty {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 0.75rem; padding: 2.5rem; color: #8193ab; text-align: center; font-size: 0.85rem;
}

/* Evidence list */
.drc-evidence-list { display: flex; flex-direction: column; gap: 0.75rem; }
.drc-ev-item {
  display: flex; gap: 0.85rem;
  background: rgba(255,255,255,0.02); border: 1px solid rgba(var(--nc-primary-rgb),0.07);
  border-radius: 8px; padding: 0.85rem 1rem;
}
.drc-ev-icon {
  width: 32px; height: 32px; border-radius: 8px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  background: rgba(var(--nc-primary-rgb),0.1); color: var(--drc-cyan);
}
.drc-ev-icon--link     { background: rgba(167,139,250,0.1); color: var(--drc-purple); }
.drc-ev-icon--document { background: rgba(34,197,94,0.1);   color: var(--drc-green); }
.drc-ev-body { flex: 1; }
.drc-ev-meta { display: flex; justify-content: space-between; margin-bottom: 0.4rem; }
.drc-ev-who  { font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem; color: var(--drc-cyan); }
.drc-ev-when { font-size: 0.72rem; color: #8193ab; }
.drc-ev-content { font-size: 0.83rem; color: #c8d6e8; line-height: 1.5; }
.drc-ev-sub     { font-size: 0.75rem; color: #8193ab; margin-top: 0.3rem; }

/* Ruling */
.drc-ruling-banner {
  border-radius: 8px; padding: 0.85rem 1rem;
  display: flex; align-items: center; justify-content: space-between;
}
.drc-ruling-banner--resolved { background: rgba(34,197,94,0.08); border: 1px solid rgba(34,197,94,0.2); color: var(--drc-green); }
.drc-ruling-banner--dismissed { background: rgba(107,114,128,0.1); border: 1px solid rgba(107,114,128,0.2); color: #9ca3af; }
.drc-ruling-banner__label { display: flex; align-items: center; gap: 0.5rem; font-weight: 600; font-size: 0.85rem; }
.drc-ruling-banner__date  { font-size: 0.75rem; opacity: 0.7; }

.drc-comp-box {
  background: rgba(var(--nc-primary-rgb),0.05); border: 1px solid rgba(var(--nc-primary-rgb),0.15);
  border-radius: 8px; padding: 1rem;
}
.drc-comp-box__header {
  display: flex; align-items: center; gap: 0.5rem;
  font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.08em; color: var(--drc-cyan);
  margin-bottom: 0.75rem;
}
.drc-comp-partial { background: rgba(245,158,11,0.15); color: #f59e0b; border-radius: 9999px; padding: 0.1rem 0.5rem; font-size: 0.65rem; }
.drc-comp-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem 1.25rem; font-size: 0.82rem; color: #c8d6e8; }
.drc-comp-amount { font-family: 'IBM Plex Mono', monospace; font-size: 1.1rem; font-weight: 700; color: var(--drc-cyan); }
.drc-comp-tx { font-family: 'IBM Plex Mono', monospace; font-size: 0.68rem; color: #8193ab; margin-top: 0.75rem; border-top: 1px solid rgba(var(--nc-primary-rgb),0.1); padding-top: 0.5rem; }

.drc-rep-box { background: rgba(167,139,250,0.05); border: 1px solid rgba(167,139,250,0.15); border-radius: 8px; padding: 1rem; }
.drc-rep-box__header { font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--drc-purple); margin-bottom: 0.75rem; }
.drc-rep-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; font-size: 0.82rem; }
.drc-rep-delta { font-family: 'IBM Plex Mono', monospace; font-size: 0.95rem; font-weight: 700; }
.drc-rep-delta--pos { color: var(--drc-green); }
.drc-rep-delta--neg { color: var(--drc-red); }
.drc-rep-range { font-size: 0.7rem; color: #8193ab; font-weight: 400; margin-left: 0.25rem; }

.drc-detail-footer {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0.85rem 1.5rem;
  border-top: 1px solid rgba(var(--nc-primary-rgb),0.1);
  flex-shrink: 0;
}
.drc-detail-footer__left, .drc-detail-footer__right { display: flex; gap: 0.6rem; }

/* Shared buttons (used in detail modal + evidence modal) */
.drc-btn {
  display: inline-flex; align-items: center; gap: 0.4rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem; font-weight: 600;
  letter-spacing: 0.1em; text-transform: uppercase;
  padding: 0.5rem 1rem;
  border-radius: 6px; border: 1px solid transparent;
  cursor: pointer; transition: all 0.15s;
}
.drc-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.drc-btn--primary { background: var(--drc-cyan); color: #060b14; border-color: var(--drc-cyan); }
.drc-btn--primary:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb),0.85); }
.drc-btn--ghost   { background: transparent; color: #8fa3be; border-color: rgba(var(--nc-primary-rgb),0.2); }
.drc-btn--ghost:hover:not(:disabled)   { background: rgba(var(--nc-primary-rgb),0.08); color: var(--drc-cyan); }
.drc-btn--success { background: rgba(34,197,94,0.12); color: var(--drc-green); border-color: rgba(34,197,94,0.3); }
.drc-btn--success:hover:not(:disabled) { background: rgba(34,197,94,0.2); }

/* Animations (shared with tp-disputes-modals) */
@keyframes tp-fade-in { from { opacity: 0; } to { opacity: 1; } }
@keyframes tp-entry   { from { opacity: 0; transform: scale(0.97) translateY(8px); } to { opacity: 1; transform: scale(1) translateY(0); } }
@keyframes drc-spin   { to { transform: rotate(360deg); } }
@keyframes tp-spin    { to { transform: rotate(360deg); } }

/* §2026-06-07 v2j — DESIGN-LANGUAGE house card. De-greys the flat --drc-surface
   (#111827) boxes → subtle primary tint + sheen + blur + soft shadow. NOTE: only
   background/blur/shadow here — .drc-card keeps its existing 1px var(--drc-border)
   AND its status `border-left` rail (open/resolved/…), so we must NOT set the
   border shorthand. Ref: PRODUCTION_DOCS/03_SERVICES/Frontend/Design_Language.md. */
.drc-stat-card, .drc-card {
  background:
    linear-gradient(168deg, rgba(255,255,255,0.09), rgba(255,255,255,0.025) 46%, rgba(255,255,255,0.004) 100%),
    rgba(10, 14, 24, 0.45);
  border-radius: 14px;
  backdrop-filter: blur(16px) saturate(1.12);
  -webkit-backdrop-filter: blur(16px) saturate(1.12);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.08), 0 20px 46px -24px rgba(0,0,0,0.95);
  transition: background .18s ease, border-color .18s ease, box-shadow .18s ease, transform .18s ease;
}
.drc-stat-card:hover, .drc-card:hover {
  border-color: rgba(var(--drc-cyan-rgb), 0.42);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.09), 0 24px 52px -22px rgba(0,0,0,0.95);
  transform: translateY(-3px);
}
/* form controls → input recipe (darker translucent, not the grey surface) */
.drc-select, .drc-search { background: rgba(4,8,14,0.55); }
/* §2026-06-07 v2k — inline monochrome icon replacing the <Icon name="mdi:lightning-bolt" /> emoji (no-emoji rule) */
.drc-inline-ic { width: 1em; height: 1em; display: inline-block; vertical-align: -0.15em; flex-shrink: 0; }
/* ═══ §v0003 polish (2 passes) ═══ */
/* pass 1 — hero stat numbers: tabular + per-value glow (inherits the stat color) */
.drc-stat-card__value { font-variant-numeric: tabular-nums; letter-spacing: -0.01em; text-shadow: 0 0 18px color-mix(in srgb, currentColor 22%, transparent); }
/* pass 2 — keyboard focus ring */
.drc-view :is(button, input, select, [tabindex]):focus-visible { outline: 2px solid rgba(var(--drc-cyan-rgb), 0.55); outline-offset: 2px; border-radius: 6px; }

/* tp-* classes used by evidence & ruling modals (imported via CSS) */
</style>
