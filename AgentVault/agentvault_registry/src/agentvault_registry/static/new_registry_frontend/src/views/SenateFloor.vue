<template>
  <div class="sn-view hm-module">
    <!-- 2026-05-07: ambient bg (matches Federation/MyAgents/AdminCanaries). -->
    <div class="sn-content">

    <!-- ── Page Header ───────────────────────────────────────────────────── -->
    <div class="sn-header">
      <div>
        <h1 class="sn-title">{{ t('senateView.title') }}</h1>
        <p class="sn-subtitle">{{ t('senateView.subtitle') }}</p>
      </div>
      <div class="sn-tabs" role="tablist">
        <button v-if="stakingTabVisible" role="tab" data-testid="sen-tab-staking" :aria-selected="activeTab === 'staking'" :class="['sn-tab', activeTab === 'staking'    && 'sn-tab--active']" @click="activeTab = 'staking'">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="sn-tab__icon"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>
          {{ t('senateView.tabs.staking') }}
        </button>
        <button data-tour="sen-tab-gov" role="tab" :aria-selected="activeTab === 'governance'" :class="['sn-tab', activeTab === 'governance' && 'sn-tab--active']" @click="activeTab = 'governance'">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="sn-tab__icon"><path d="M3 3h18v18H3z"/><path d="M8 12l3 3 5-5"/></svg>
          {{ t('senateView.tabs.governance') }}
        </button>
        <button v-if="authStore.isAdmin" role="tab" :aria-selected="activeTab === 'funding'" :class="['sn-tab', activeTab === 'funding' && 'sn-tab--active']" @click="activeTab = 'funding'; fetchFundingRequests()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="sn-tab__icon"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg>
          {{ t('senateView.tabs.funding') }}
        </button>
        <button role="tab" :aria-selected="activeTab === 'federation'" :class="['sn-tab', activeTab === 'federation' && 'sn-tab--active']" @click="activeTab = 'federation'; fetchFederationProposals()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="sn-tab__icon"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/></svg>
          {{ t('senateView.tabs.federation') }}
        </button>
        <button v-if="commonsOn" role="tab" data-testid="sen-tab-commons" :aria-selected="activeTab === 'commons'" :class="['sn-tab', activeTab === 'commons' && 'sn-tab--active']" @click="activeTab = 'commons'">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="sn-tab__icon"><path d="M12 3v18"/><path d="M5 7h14"/><path d="M5 7l-3 7a4 4 0 006 0z"/><path d="M19 7l-3 7a4 4 0 006 0z"/></svg>
          {{ t('commons.tab', 'Commons') }}
        </button>
      </div>
    </div>

    <!-- ── Loading ────────────────────────────────────────────────────────── -->
    <div v-if="isLoading" class="sn-loader">
      <div class="sn-loader__ring"></div>
      <span>{{ t('senateView.loading') }}</span>
    </div>

    <template v-else>

      <!-- ════════════════════════════════════════════════════════════════════
           LOCKS TAB
      ════════════════════════════════════════════════════════════════════ -->
      <div v-if="activeTab === 'staking'" class="sn-tab-content">

        <!-- Per-tab loading. §MEMBERSHIP (V0564): also until the registry's config says whether the tab exists. -->
        <div v-if="!stakingDecided" class="sn-loader">
          <div class="sn-loader__ring"></div>
          <span>{{ t('senateView.loadingStaking') }}</span>
        </div>
        <template v-else-if="stakingTabVisible">

        <!-- §MEMBERSHIP (V0564): where no new lock opens, say so, and that a lock gives no weight where the registry
             votes by membership; the positions below can still be unlocked. -->
        <div v-if="!senateStakingOn" class="sn-staking-off" data-testid="sen-staking-off">
          <p>{{ t('senateView.staking.offNotice') }}</p>
          <p v-if="lockSentence(senateRegistryCfg) === 'no_weight_member'">{{ t('senateView.staking.noPositionsSubMember') }}</p>
        </div>

        <!-- Stat cards. P5.1 (2026-05-08): the cyan stat uses theme tokens
             so it cycles to sovereign red / custom accent. The other 3
             are semantic colors (green=payouts, purple=payout rate, amber=positions)
             intentionally NOT theme-cycled — they encode meaning. -->
        <div class="sn-stats">
          <div class="sn-stat-card">
            <div class="sn-stat-card__accent" style="background:var(--nc-primary, #00d2d2)"></div>
            <div class="sn-stat-card__body">
              <div class="sn-stat-card__label">{{ t('senateView.stats.yourStaked') }}</div>
              <div class="sn-stat-card__value" style="color:var(--nc-primary, #00d2d2)">{{ stakingReadFailed ? '—' : formatNum(stakingStore.totalStaked) }} {{ stakingReadFailed ? '' : localCurrency }}</div>
            </div>
          </div>
          <div v-if="senateRatesOn" class="sn-stat-card">
            <div class="sn-stat-card__accent" style="background:rgb(34,197,94)"></div>
            <div class="sn-stat-card__body">
              <div class="sn-stat-card__label">{{ t('senateView.stats.rewardsAvailable') }}</div>
              <div class="sn-stat-card__value" style="color:rgb(34,197,94)">{{ stakingReadFailed ? '—' : formatNum(stakingStore.availableRewards) }} {{ stakingReadFailed ? '' : localCurrency }}</div>
            </div>
          </div>
          <div v-if="senateRatesOn" class="sn-stat-card">
            <div class="sn-stat-card__accent" style="background:rgb(167,139,250)"></div>
            <div class="sn-stat-card__body">
              <div class="sn-stat-card__label">{{ t('senateView.stats.bestApy') }}</div>
              <div class="sn-stat-card__value" style="color:rgb(167,139,250)">{{ stakingStore.bestApy || stakingStore.averageApy }}%</div>
            </div>
          </div>
          <div class="sn-stat-card">
            <div class="sn-stat-card__accent" style="background:rgb(251,191,36)"></div>
            <div class="sn-stat-card__body">
              <div class="sn-stat-card__label">{{ t('senateView.stats.activePositions') }}</div>
              <div class="sn-stat-card__value" style="color:rgb(251,191,36)">{{ stakingReadFailed || !stakingStore.positionsReadable ? '—' : stakingStore.activePositions.length }}</div>
            </div>
          </div>
        </div>

        <!-- Action buttons -->
        <div class="sn-action-bar">
          <button v-if="senateStakingOn" class="sn-cta-btn" @click="showStakeModal = true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="width:14px;height:14px"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            {{ t('senateView.staking.stakeTeg') }}
          </button>
          <button
            v-if="senateRatesOn"
            class="sn-ghost-btn"
            :disabled="parseFloat(stakingStore.availableRewards) === 0 || isActing"
            @click="handleClaimRewards"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><polyline points="20 12 20 22 4 22 4 12"/><rect x="2" y="7" width="20" height="5"/><line x1="12" y1="22" x2="12" y2="7"/><path d="M12 7H7.5a2.5 2.5 0 010-5C11 2 12 7 12 7z"/><path d="M12 7h4.5a2.5 2.5 0 000-5C13 2 12 7 12 7z"/></svg>
            {{ t('senateView.staking.claimAll') }}
          </button>
        </div>

        <!-- Positions -->
        <div class="sn-section">
          <div class="sn-section-title">{{ t('senateView.staking.positions') }}</div>

          <ReadFailedNotice v-if="stakingReadFailed || positionsUnread" :retry="readMyStaking" data-testid="sn-staking-failed" />
          <div v-else-if="stakingStore.activePositions.length === 0" class="sn-empty">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="width:40px;height:40px;color:#7b91b2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>
            <p class="sn-empty__title">{{ t('senateView.staking.noPositions') }}</p>
            <p class="sn-empty__sub">{{ lockSentence(senateRegistryCfg) === 'no_weight_member' ? t('senateView.staking.noPositionsSubMember') : t('senateView.staking.noPositionsSub') }}</p>
          </div>

          <div v-else class="sn-positions-grid">
            <div
              v-for="pos in visiblePositions"
              :key="pos.id"
              class="sn-pos-card"
              :class="posCardClass(pos)"
            >
              <div class="sn-pos-card__head">
                <span class="sn-pos-card__amount">{{ formatNum(pos.amount) }} {{ localCurrency }}</span>
                <span v-if="senateRatesOn" class="sn-pos-apy-badge">{{ pos.apy }}% payout</span>
              </div>
              <div class="sn-pos-card__type">{{ pos.lockPeriod === 0 ? t('senateView.staking.flexible') : pos.lockPeriod + t('senateView.staking.dLock') }}</div>

              <div class="sn-pos-rows">
                <div v-if="senateRatesOn" class="sn-pos-row">
                  <span>{{ t('senateView.staking.rewardsEarned') }}</span>
                  <span style="color:rgb(34,197,94)">+{{ formatNum(posRewards(pos)) }} {{ localCurrency }}</span>
                </div>
                <div class="sn-pos-row">
                  <span>{{ t('senateView.staking.started') }}</span>
                  <span>{{ timeAgo(pos.startDate || pos.staked_at) }}</span>
                </div>
                <div class="sn-pos-row">
                  <span>{{ t('senateView.staking.unlocks') }}</span>
                  <span v-if="pos.canUnstake || pos.lockPeriod === 0" style="color:rgb(34,197,94);font-weight:600">{{ t('senateView.staking.readyToUnstake') }}</span>
                  <span v-else style="color:rgb(251,191,36)">{{ timeAgo(pos.unlockDate) }}</span>
                </div>
              </div>

              <button
                v-if="pos.canUnstake || pos.lockPeriod === 0"
                class="sn-unstake-btn"
                @click="handleUnstake(pos)"
              >
                <svg class="sn-btn-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.5-2"/></svg>{{ t('senateView.staking.unstake') }}
              </button>
              <div v-else class="sn-locked-bar">
                <svg class="sn-btn-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>{{ t('senateView.staking.locked', { time: lockedFor(pos.unlockDate) }) }}
              </div>
            </div>
          </div>

          <!-- Load more positions -->
          <div v-if="hasMorePositions" class="sn-load-more">
            <button class="sn-ghost-btn" @click="stakingPositionsLimit += 20">
              {{ t('senateView.staking.showMore', { count: stakingStore.activePositions.length - stakingPositionsLimit }) }}
            </button>
          </div>
        </div>

        <!-- ── Lock Tiers ─────────────────────────────────────────────────── -->
        <div v-if="senateRatesOn" class="sn-section">
          <div class="sn-section-title">{{ t('senateView.staking.apyTiers') }}</div>
          <div class="sn-tier-grid" :style="{ gridTemplateColumns: `repeat(${stakingStore.apyTiers.length}, 1fr)` }">
            <div
              v-for="tier in stakingStore.apyTiers"
              :key="tier.lockPeriod"
              class="sn-tier-card"
              :class="tier.lockPeriod === 0 ? 'sn-tier-card--flex' : 'sn-tier-card--lock'"
              @click="openStakeWithTier(tier)"
            >
              <!-- Icon -->
              <div class="sn-tier-card__icon">
                <svg v-if="tier.lockPeriod === 0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
                <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>
              </div>

              <!-- Period label -->
              <div class="sn-tier-card__period">
                {{ tier.lockPeriod === 0 ? t('senateView.staking.flexible') : tier.lockPeriod + ' ' + t('senateView.staking.days') }}
              </div>

              <!-- Payout rate — headline number -->
              <div class="sn-tier-card__apy">{{ tier.apy }}%</div>
              <div class="sn-tier-card__apy-label">{{ t('senateView.apyLabel') }}</div>

              <!-- Lock bonus or flex badge -->
              <div v-if="tier.lockPeriod === 0" class="sn-tier-card__badge sn-tier-card__badge--flex">
                {{ t('senateView.staking.anytime') }}
              </div>
              <div v-else class="sn-tier-card__badge sn-tier-card__badge--bonus">
                {{ t('senateView.staking.bonus', { pct: tier.lockPremium }) }}
              </div>

              <!-- Description -->
              <div class="sn-tier-card__desc">{{ tier.description }}</div>

              <!-- Lock CTA -->
              <div class="sn-tier-card__cta">{{ t('senateView.stakeCta') }}</div>
            </div>
          </div>
        </div>

        </template>
      </div><!-- /staking tab -->

      <!-- ════════════════════════════════════════════════════════════════════
           GOVERNANCE TAB
      ════════════════════════════════════════════════════════════════════ -->
      <div v-else-if="activeTab === 'governance'" class="sn-tab-content">

        <!-- Per-tab loading -->
        <div v-if="governanceLoading" class="sn-loader">
          <div class="sn-loader__ring"></div>
          <span>{{ t('senateView.loadingGovernance') }}</span>
        </div>
        <template v-else>

        <!-- Stat cards -->
        <div class="sn-stats">
          <div class="sn-stat-card" data-tour="sen-power">
            <div class="sn-stat-card__accent" style="background:var(--sn-cyan)"></div>
            <div class="sn-stat-card__body">
              <div class="sn-stat-card__label">{{ memberMode ? t('membership.senate.weightCard', 'Your vote weight') : t('senateView.governance.votingPower') }}</div>
              <div class="sn-stat-card__value" style="color:var(--sn-cyan)" data-testid="sen-power-value">{{ memberMode ? memberWeightText : governanceStore.myVotingPower }}</div>
            </div>
          </div>
          <div class="sn-stat-card">
            <div class="sn-stat-card__accent" style="background:rgb(34,197,94)"></div>
            <div class="sn-stat-card__body">
              <div class="sn-stat-card__label">{{ t('senateView.governance.activeProposals') }}</div>
              <div class="sn-stat-card__value" style="color:rgb(34,197,94)">{{ activeProposalsCount }}</div>
            </div>
          </div>
          <div class="sn-stat-card">
            <div class="sn-stat-card__accent" style="background:rgb(167,139,250)"></div>
            <div class="sn-stat-card__body">
              <div class="sn-stat-card__label">{{ t('senateView.governance.totalVoters') }}</div>
              <div class="sn-stat-card__value" style="color:rgb(167,139,250)" data-testid="sen-total-voters"
                   :title="t('senateView.governance.totalVotersHint', 'Every agent that has cast a vote on this registry, members or not, since it began')">{{ fmtCount(governanceStore.totalVoters ?? 0) }}</div>
            </div>
          </div>
          <div class="sn-stat-card">
            <div class="sn-stat-card__accent" style="background:rgb(251,191,36)"></div>
            <div class="sn-stat-card__body">
              <div class="sn-stat-card__label">{{ memberMode ? t('membership.senate.membersCard', 'Members') : t('senateView.governance.networkVePower') }}</div>
              <div class="sn-stat-card__value" style="color:rgb(251,191,36)">{{ memberMode ? fmtCount(membershipStats?.members ?? 0) : formatNum(governanceStore.networkVePower) }}</div>
            </div>
          </div>
        </div>

        <!-- veToken breakdown -->
        <div v-if="!memberMode && governanceStore.powerPositions.length > 0" class="sn-vepower-box" data-tour="sen-vepower">
          <div class="sn-vepower-box__title">{{ t('senateView.governance.vePowerByPosition') }}</div>
          <div class="sn-vepower-list">
            <div v-for="pos in governanceStore.powerPositions" :key="pos.stake_id" class="sn-vepower-row">
              <div class="sn-vepower-row__left">
                <span class="sn-vepower-row__amount">{{ formatNum(pos.amount) }} {{ localCurrency }}</span>
                <span class="sn-vepower-row__sep">·</span>
                <span class="sn-vepower-row__type">{{ pos.lock_days === 0 ? t('senateView.staking.flexible') : pos.lock_days + t('senateView.staking.dLock') }}</span>
                <span v-if="pos.remaining_days > 0" class="sn-vepower-row__rem">({{ Math.round(pos.remaining_days) }}d remaining)</span>
              </div>
              <span class="sn-vepower-row__ve" :class="pos.ve_power > 0 ? 'sn-vepower-row__ve--active' : ''">
                {{ pos.ve_power }} vote power
              </span>
            </div>
          </div>
        </div>

        <!-- §MEMBERSHIP: am I a member, with which weight, or the one next step -->
        <MembershipPanel v-if="memberMode" style="margin-bottom:1rem" />
        <!-- §MEMBERSHIP: the agent you act as needs gov.vote (the governor role) before a member's vote can be cast -->
        <VotePermissionNotice v-if="memberMode" :did="actingAgentDid" :refused="voteRefusedForPermission" style="margin-bottom:1rem" @allowed="onVoteAllowed" />

        <!-- Command bar -->
        <div class="sn-gov-bar">
          <!-- Filter pills -->
          <div class="sn-pills" data-tour="sen-filters">
            <button
              v-for="f in proposalFilters" :key="f.id"
              :class="['sn-pill', proposalFilter === f.id && 'sn-pill--active']"
              @click="proposalFilter = f.id"
            >
              {{ f.label }}
              <span v-if="f.count > 0" class="sn-pill__badge">{{ f.count }}</span>
            </button>
          </div>

          <div style="display:flex;gap:0.5rem;align-items:center">
            <!-- Refresh -->
            <button class="sn-icon-btn" title="Refresh" @click="refreshGovernance">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg>
            </button>
            <!-- Create proposal -->
            <button class="sn-cta-btn" data-tour="sen-create" @click="showProposalModal = true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="width:14px;height:14px"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              {{ t('senateView.governance.createProposal') }}
            </button>
          </div>
        </div>

        <!-- Proposals list -->
        <!-- §FESUITE (the failing-reads census): with every read failed this said "No proposals found" while the floor had
             proposals; nothing read is not none -->
        <ReadFailedNotice v-if="governanceStore.proposalsFailed && !governanceStore.proposals.length" :retry="() => governanceStore.fetchProposals(1)" />
        <div v-else-if="filteredProposals.length === 0" class="sn-empty">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="width:40px;height:40px;color:#7b91b2"><path d="M3 3h18v18H3z"/><path d="M8 12l3 3 5-5"/></svg>
          <p class="sn-empty__title">{{ t('senateView.governance.noProposals') }}</p>
          <p class="sn-empty__sub">{{ proposalFilter !== 'all' ? t('senateView.governance.clearFilter') : t('senateView.governance.createFirst') }}</p>
        </div>

        <div v-else class="sn-proposals-list">
          <div
            v-for="proposal in filteredProposals"
            :key="proposal.id"
            class="sn-proposal-card"
            :class="proposalCardClass(proposal)"
            data-tour="sen-proposal"
            :data-id="proposal.id"
          >
            <!-- Header row -->
            <div class="sn-proposal-card__head">
              <div class="sn-proposal-card__head-left">
                <span class="sn-prop-id">#{{ proposal.id }}</span>
                <span :class="['sn-prop-status-pill', `sn-prop-status-pill--${proposalStatus(proposal).toLowerCase()}`]">
                  {{ proposalStatus(proposal) }}
                </span>
                <span v-if="failureReason(proposal)" class="sn-prop-reason" data-testid="sen-fail-reason" :data-reason="failureReason(proposal)">
                  {{ failureReason(proposal) === 'quorum_not_met' ? t('senateView.governance.failQuorum', 'quorum not met') : t('senateView.governance.failMajority', 'majority against') }}
                </span>
                <span :class="['sn-prop-type-pill', proposal.proposalType === 'policy_change' ? 'sn-prop-type-pill--policy' : 'sn-prop-type-pill--standard']">
                  {{ proposal.proposalType === 'policy_change' ? t('senateView.governance.policyChange') : t('senateView.governance.standard') }}
                </span>
              </div>
              <div class="sn-proposal-card__head-right">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:13px;height:13px;flex-shrink:0"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                <span>{{ getRemainingTime(proposal.votingEnd || proposal.endTime) }}</span>
              </div>
            </div>

            <!-- Title & proposer -->
            <div class="sn-proposal-card__title">{{ proposal.title }}</div>
            <div class="sn-proposal-card__proposer">by {{ shortDid(proposal.proposer || proposal.proposer_did) }}</div>

            <!-- Description -->
            <p class="sn-proposal-card__desc">{{ truncate(proposal.description, 160) }}</p>

            <!-- Vote bar -->
            <div class="sn-vote-bar-section">
              <div class="sn-vote-counts">
                <span class="sn-vote-count sn-vote-count--for" data-testid="sen-votes-for">
                  <span class="sn-vote-mark">✓</span> {{ voteAmount(proposal.votes?.for || proposal.votes_for || '0', proposal) }} {{ t('senateView.governance.for') }}
                </span>
                <span class="sn-vote-count sn-vote-count--against">
                  <span class="sn-vote-mark">✗</span> {{ voteAmount(proposal.votes?.against || proposal.votes_against || '0', proposal) }} {{ t('senateView.governance.against') }}
                </span>
              </div>
              <div class="sn-vote-bar-track">
                <div
                  class="sn-vote-bar-fill sn-vote-bar-fill--for"
                  :style="{ width: forPct(proposal) + '%' }"
                ></div>
                <div
                  class="sn-vote-bar-fill sn-vote-bar-fill--against"
                  :style="{ width: againstPct(proposal) + '%', left: forPct(proposal) + '%' }"
                ></div>
                <!-- Quorum threshold marker -->
                <div
                  v-if="quorumMarkerLeft(proposal.quorumPercent) != null"
                  class="sn-quorum-marker"
                  :style="{ left: quorumMarkerLeft(proposal.quorumPercent) + '%' }"
                  :title="'Quorum at ' + proposal.quorumPercent + '%'"
                ></div>
              </div>
              <div class="sn-quorum-label" data-testid="sen-quorum">
                {{ t('senateView.governance.quorum') }} {{ getQuorumDisplay(proposal) }}
              </div>
            </div>

            <!-- Actions. §COCKPITDESK (2026-10-15), the camera: a decided proposal you did not vote on drew this row empty,
                 an empty band under every passed card; it shows only with something in it. -->
            <div v-if="governanceStore.hasVoted(proposal.id) || isVotingActive(proposal) || proposalStatus(proposal) === 'Ended'"
                 class="sn-proposal-card__foot">
              <!-- Already voted -->
              <span
                v-if="governanceStore.hasVoted(proposal.id)"
                class="sn-voted-badge"
                :class="governanceStore.getMyVote(proposal.id)?.choice === 'for' ? 'sn-voted-badge--for' : 'sn-voted-badge--against'"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="width:12px;height:12px"><polyline points="20 6 9 17 4 12"/></svg>
                {{ t('senateView.governance.voted') }} {{ governanceStore.getMyVote(proposal.id)?.choice === 'for' ? t('senateView.governance.for') : t('senateView.governance.against') }}
              </span>

              <div style="display:flex;gap:0.5rem;align-items:center">
                <!-- Vote button -->
                <button
                  v-if="!governanceStore.hasVoted(proposal.id) && isVotingActive(proposal)"
                  class="sn-vote-btn"
                  data-tour="sen-vote"
                  @click="handleVote(proposal)"
                >
                  {{ t('senateView.governance.vote') }}
                </button>

                <!-- Finalize / tally -->
                <button
                  v-if="proposalStatus(proposal) === 'Ended'"
                  class="sn-tally-btn"
                  data-tour="sen-tally"
                  @click="handleTally(proposal)"
                >
                  <Icon name="mdi:scale-balance" /> {{ t('senateView.governance.finalize') }}
                </button>
              </div>
            </div>

          </div>
        </div>

        </template>
        <!-- Auto-Tally Config (Admin Only) -->
        <div v-if="authStore.isAdmin" class="sn-section" style="margin-top: 1.5rem;">
          <div class="sn-section-title" style="display:flex;align-items:center;justify-content:space-between;">
            <span>{{ t('senateView.autoTally.title') }}</span>
            <span style="font-size:0.65rem;color:#78808e;font-weight:400;">{{ t('senateView.autoTally.adminNote') }}</span>
          </div>
          <div style="display:flex;align-items:center;gap:1.5rem;padding:1rem;background:rgba(var(--nc-primary-rgb),0.03);border:1px solid rgba(var(--nc-primary-rgb),0.08);border-radius:0.5rem;">
            <div style="display:flex;align-items:center;gap:0.5rem;">
              <label style="font-size:0.8rem;color:#9ca3af;">{{ t('senateView.autoTally.enabled') }}</label>
              <button
                @click="toggleAutoTally"
                :style="{
                  padding: '4px 14px', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600, border: 'none', cursor: 'pointer',
                  background: autoTallyConfig.enabled ? 'rgba(74,222,128,0.15)' : 'rgba(239,68,68,0.15)',
                  color: autoTallyConfig.enabled ? '#4ade80' : '#f87171'
                }"
              >{{ autoTallyConfig.enabled ? 'ON' : 'OFF' }}</button>
            </div>
            <div style="display:flex;align-items:center;gap:0.5rem;">
              <label for="senatefloor-sel-429" style="font-size:0.8rem;color:#9ca3af;">{{ t('senateView.autoTally.interval') }}</label>
              <select id="senatefloor-sel-429" v-model="autoTallyInterval" @change="updateAutoTallyInterval" style="background:#111827;color:#f9fafb;border:1px solid rgba(255,255,255,0.1);border-radius:4px;padding:3px 8px;font-size:0.78rem;">
                <option :value="30">30s</option>
                <option :value="60">60s</option>
                <option :value="120">2 min</option>
                <option :value="300">5 min</option>
                <option :value="600">10 min</option>
              </select>
            </div>
            <span style="font-size:0.68rem;color:#728194;margin-left:auto;">
              Source: {{ autoTallyConfig.source || 'env' }}
            </span>
          </div>
        </div>

      </div><!-- /governance tab -->

      <!-- ════════════════════════════════════════════════════════════════════
           FUNDING TAB (Admin Only)
      ════════════════════════════════════════════════════════════════════ -->
      <div v-if="activeTab === 'funding' && authStore.isAdmin" class="sn-tab-content">

        <!-- Stat cards -->
        <div class="sn-stats">
          <div class="sn-stat-card">
            <div class="sn-stat-card__accent" style="background:rgb(251,191,36)"></div>
            <div class="sn-stat-card__body">
              <div class="sn-stat-card__label">{{ t('senateView.funding.pendingRequests') }}</div>
              <div class="sn-stat-card__value" style="color:rgb(251,191,36)">{{ pendingFundingRequests.length }}</div>
            </div>
          </div>
          <div class="sn-stat-card">
            <div class="sn-stat-card__accent" style="background:var(--sn-cyan)"></div>
            <div class="sn-stat-card__body">
              <div class="sn-stat-card__label">{{ t('senateView.funding.totalApproved') }}</div>
              <div class="sn-stat-card__value" style="color:var(--sn-cyan)">{{ formatNum(totalApprovedAVT) }} {{ localCurrency }}</div>
            </div>
          </div>
          <div class="sn-stat-card">
            <div class="sn-stat-card__accent" style="background:rgb(34,197,94)"></div>
            <div class="sn-stat-card__body">
              <div class="sn-stat-card__label">{{ t('senateView.funding.totalFunded') }}</div>
              <div class="sn-stat-card__value" style="color:rgb(34,197,94)">{{ formatNum(totalFundedAVT) }} {{ localCurrency }}</div>
            </div>
          </div>
          <div class="sn-stat-card">
            <div class="sn-stat-card__accent" style="background:rgb(148,163,184)"></div>
            <div class="sn-stat-card__body">
              <div class="sn-stat-card__label">{{ tp('senateView.funding.pendingAvt', 'Pending {unit}', { unit: localCurrency }) }}</div>
              <div class="sn-stat-card__value" style="color:rgb(148,163,184)">{{ formatNum(totalPendingAVT) }} {{ localCurrency }}</div>
            </div>
          </div>
        </div>

        <!-- Loading -->
        <div v-if="fundingLoading" class="sn-empty">
          <div class="sn-loader__ring"></div>
          <p class="sn-empty__sub">{{ t('senateView.funding.loading') }}</p>
        </div>

        <!-- Pending Requests Table -->
        <div v-else class="sn-section">
          <div class="sn-section-title">{{ t('senateView.funding.pendingSection') }}</div>

          <ReadFailedNotice v-if="fundingFailed" dense :retry="fetchFundingRequests" />
          <div v-else-if="pendingFundingRequests.length === 0" class="sn-empty">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="width:40px;height:40px;color:#7b91b2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg>
            <p class="sn-empty__title">{{ t('senateView.funding.noPending') }}</p>
            <p class="sn-empty__sub">{{ t('senateView.funding.allCaughtUp') }}</p>
          </div>

          <div v-else class="fund-table-wrap">
            <table class="fund-table">
              <thead>
                <tr>
                  <th>{{ t('senateView.funding.colRequester') }}</th>
                  <th>{{ t('senateView.funding.colAmount') }}</th>
                  <th>{{ t('senateView.funding.colReason') }}</th>
                  <th>{{ t('senateView.funding.colDate') }}</th>
                  <th>{{ t('senateView.funding.colActions') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="req in pendingFundingRequests" :key="req.id">
                  <td class="fund-td-did" :title="req.requester_did || req.agent_did">{{ fundingShortDid(req.requester_did || req.agent_did) }}</td>
                  <td class="fund-td-amount">{{ formatNum(req.requested_amount || req.amount) }} {{ localCurrency }}</td>
                  <td class="fund-td-reason" :title="req.reason">{{ truncate(req.reason || '', 60) }}</td>
                  <td class="fund-td-date">{{ fundingFormatDate(req.created_at) }}</td>
                  <td class="fund-td-actions">
                    <!-- Approve flow -->
                    <template v-if="approveInputId === req.id">
                      <input
                        v-model.number="approveAmount"
                        type="number"
                        min="1"
                        class="fund-inline-input"
                        placeholder="Amount"
                      />
                      <button class="fund-btn fund-btn--confirm" :disabled="fundingActing" @click="approveFundingRequest(req.id)">{{ t('common.ok') }}</button>
                      <button class="fund-btn fund-btn--cancel" @click="approveInputId = null">✕</button>
                    </template>
                    <!-- Reject flow -->
                    <template v-else-if="rejectInputId === req.id">
                      <input
                        v-model="rejectReason"
                        type="text"
                        class="fund-inline-input fund-inline-input--wide"
                        :placeholder="t('senateView.funding.reasonPlaceholder')"
                      />
                      <button class="fund-btn fund-btn--reject-confirm" :disabled="fundingActing" @click="rejectFundingRequest(req.id)">{{ t('common.ok') }}</button>
                      <button class="fund-btn fund-btn--cancel" @click="rejectInputId = null">✕</button>
                    </template>
                    <!-- Default buttons -->
                    <template v-else>
                      <button class="fund-btn fund-btn--approve" @click="openApproveInput(req)">{{ t('common.approve') }}</button>
                      <button class="fund-btn fund-btn--reject" @click="openRejectInput(req)">{{ t('common.reject') }}</button>
                    </template>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- History Section -->
        <div v-if="pastFundingRequests.length > 0" class="sn-section" style="margin-top:1.5rem">
          <div class="sn-section-title">{{ t('senateView.funding.historySection') }}</div>
          <div class="fund-table-wrap">
            <table class="fund-table">
              <thead>
                <tr>
                  <th>{{ t('senateView.funding.colRequester') }}</th>
                  <th>{{ t('senateView.funding.colAmount') }}</th>
                  <th>{{ t('senateView.funding.colStatus') }}</th>
                  <th>{{ t('senateView.funding.colReason') }}</th>
                  <th>{{ t('senateView.funding.colDate') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="req in pastFundingRequests" :key="req.id">
                  <td class="fund-td-did" :title="req.requester_did || req.agent_did">{{ fundingShortDid(req.requester_did || req.agent_did) }}</td>
                  <td class="fund-td-amount">{{ formatNum(req.approved_amount || req.requested_amount || req.amount) }} {{ localCurrency }}</td>
                  <td>
                    <span
                      class="fund-status-badge"
                      :style="{ background: fundingStatusColor(req.status) + '20', color: fundingStatusColor(req.status), borderColor: fundingStatusColor(req.status) + '40' }"
                    >{{ (req.status || 'unknown').toUpperCase() }}</span>
                  </td>
                  <td class="fund-td-reason" :title="req.reason">{{ truncate(req.reason || '', 40) }}</td>
                  <td class="fund-td-date">{{ fundingFormatDate(req.created_at) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

      </div><!-- /funding tab -->

      <!-- ═══ FEDERATION TAB ═══════════════════════════════════════════════ -->
      <div v-else-if="activeTab === 'federation'" class="sn-tab-content">
        <div v-if="federationLoading" class="sn-loader"><div class="sn-loader__ring"></div><span>{{ t('senateView.federation.loading') }}</span></div>
        <template v-else>
          <!-- Stats -->
          <div class="sn-stats">
            <div class="sn-stat-card"><div class="sn-stat-card__accent" style="background: var(--sn-cyan)"></div><div class="sn-stat-card__body"><div class="sn-stat-card__label">{{ t('senateView.federation.totalProposals') }}</div><div class="sn-stat-card__value" style="color: var(--sn-cyan)">{{ fedStats.total }}</div></div></div>
            <div class="sn-stat-card"><div class="sn-stat-card__accent" style="background: var(--sn-green)"></div><div class="sn-stat-card__body"><div class="sn-stat-card__label">{{ t('senateView.federation.activeVoting') }}</div><div class="sn-stat-card__value" style="color: var(--sn-green)">{{ fedStats.voting }}</div></div></div>
            <div class="sn-stat-card"><div class="sn-stat-card__accent" style="background: var(--sn-amber)"></div><div class="sn-stat-card__body"><div class="sn-stat-card__label">{{ t('senateView.federation.passedApplied') }}</div><div class="sn-stat-card__value" style="color: var(--sn-amber)">{{ fedStats.passed }}</div></div></div>
            <div class="sn-stat-card"><div class="sn-stat-card__accent" style="background: var(--sn-red)"></div><div class="sn-stat-card__body"><div class="sn-stat-card__label">{{ t('senateView.federation.vetoed') }}</div><div class="sn-stat-card__value" style="color: var(--sn-red)">{{ fedStats.vetoed }}</div></div></div>
          </div>

          <!-- Filters -->
          <div class="sn-section">
            <div style="display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 16px;">
              <button v-for="f in ['all','VOTING','PASSED','FAILED','VETOED','APPLIED']" :key="f"
                :class="['sn-pill', federationFilter === f && 'sn-pill--active']"
                @click="federationFilter = f">
                {{ f === 'all' ? t('senateView.federation.ballots.filterAll', 'All') : fedStatusLabel(f) }}
              </button>
            </div>
          </div>

          <!-- §MCPTEST30 (V0557): ballot proposals other registries host, where this registry casts its own ballot -->
          <div v-if="ballotModeHere && peerOpen.length" class="sn-fed-peers" data-testid="fed-ballots-at-peers">
            <h3 class="sn-fed-peers__title">{{ t('senateView.federation.ballots.atPeers', 'Open at other registries') }}</h3>
            <div v-for="x in peerOpen" :key="x.host.host + '/' + x.proposal.id" class="sn-proposal-card sn-proposal-card--active"
                 data-testid="fed-peer-proposal" :data-host="x.host.name" :data-proposal="x.proposal.id">
              <div class="sn-proposal-card__head" data-testid="senate-fed-head">
                <div class="sn-proposal-card__head-left">
                  <span class="sn-prop-id">#FED</span>
                  <span :class="['sn-prop-status-pill', fedStatusPill('VOTING')]">{{ fedStatusLabel('VOTING') }}</span>
                  <span class="sn-prop-type-pill sn-prop-type-pill--policy">{{ t('senateView.federation.ballots.typeBallot', 'One ballot per registry') }}</span>
                </div>
                <div v-if="x.proposal.end_timestamp" class="sn-proposal-card__head-right">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:13px;height:13px;flex-shrink:0"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                  <span>{{ tp('senateView.federation.ballots.endsIn', 'ends {when}', { when: dayjs(x.proposal.end_timestamp).fromNow() }) }}</span>
                </div>
              </div>
              <h3 class="sn-proposal-card__title">{{ x.proposal.title }}</h3>
              <p class="sn-fed-origin">{{ tp('senateView.federation.ballots.hostedAt', 'Hosted by {host}', { host: x.host.name }) }}</p>
              <p class="sn-proposal-card__desc">{{ x.proposal.description?.slice(0, 200) }}{{ (x.proposal.description?.length || 0) > 200 ? '…' : '' }}</p>
              <FederationBallotPanel :proposal-id="String(x.proposal.id)" status="VOTING" :end-timestamp="x.proposal.end_timestamp ?? null"
                :summary="null" :host-key="x.host.host" :host-name="x.host.name" :hosted="false" :open="x.proposal"
                :hosts="ballotHosts" :my-registry-id="myRegistryId" :is-admin="authStore.isAdmin" :has-members="hasMembers"
                @changed="fetchFederationProposals" @open-local="openLocalVote" />
            </div>
          </div>
          <p v-for="h in (ballotModeHere ? peerBallotErrors : [])" :key="'err-' + h.host" class="sn-fed-peers__error" data-testid="fed-peer-unreadable">
            {{ tp('senateView.federation.ballots.peerUnreadable', "{host}'s open ballots could not be read: {error}", { host: h.name, error: h.error || '' }) }}
          </p>

          <!-- Proposals -->
          <ReadFailedNotice v-if="fedFailed && !federationProposals.length" :retry="fetchFederationProposals" data-testid="sn-fed-failed" />
          <p v-else-if="filteredFedProposals.length === 0 && federationFilter === 'all' && ballotModeHere && peerOpen.length" class="sn-fed-peers__none" data-testid="fed-none-hosted">
            {{ t('senateView.federation.ballots.noneHostedHere', 'This registry hosts no federation proposals of its own.') }}
          </p>
          <div v-else-if="filteredFedProposals.length === 0" class="sn-empty">
            <p style="font-size: 1.3rem; margin-bottom: 8px;">{{ t('senateView.federation.noProposals') }}{{ federationFilter !== 'all' ? ' ' + t('senateView.federation.withStatus') + ' ' + fedStatusLabel(federationFilter) : '' }}</p>
            <p style="color: var(--muted); font-size: 0.85rem;">{{ t('senateView.federation.elevateHint') }}</p>
          </div>

          <div v-else class="sn-proposals-list">
            <div v-for="p in filteredFedProposals" :key="p.id" class="sn-proposal-card" :class="fedStatusClass(p.status)">
              <div class="sn-proposal-card__head" data-testid="senate-fed-head">
                <div class="sn-proposal-card__head-left">
                  <span class="sn-prop-id">#FED</span>
                  <span :class="['sn-prop-status-pill', fedStatusPill(p.status)]" data-testid="fed-card-status" :data-status="p.status">{{ fedStatusLabel(p.status) }}</span>
                  <span :class="['sn-prop-type-pill', p.ballot_mode ? 'sn-prop-type-pill--policy' : 'sn-prop-type-pill--standard']">{{ p.ballot_mode ? t('senateView.federation.ballots.typeBallot', 'One ballot per registry') : t('senateView.federation.ballots.typePolicy', 'Federation policy') }}</span>
                </div>
                <div v-if="p.status === 'VOTING' && p.end_timestamp" class="sn-proposal-card__head-right">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:13px;height:13px;flex-shrink:0"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                  <span>{{ tp('senateView.federation.ballots.endsIn', 'ends {when}', { when: dayjs(p.end_timestamp).fromNow() }) }}</span>
                </div>
              </div>
              <h3 class="sn-proposal-card__title">{{ p.title }}</h3>
              <p class="sn-fed-origin">{{ t('senateView.federation.elevatedBy') }} <strong>{{ fedRaisedBy(p) }}</strong>
                <span v-if="p.origin_proposal_id"> · {{ tp('senateView.federation.ballots.localProposal', 'local proposal #{id}', { id: p.origin_proposal_id }) }}</span>
              </p>
              <p class="sn-proposal-card__desc">{{ p.description?.slice(0, 200) }}{{ (p.description?.length || 0) > 200 ? '…' : '' }}</p>

              <!-- Vote bar -->
              <div v-if="!p.ballot_mode && (p.votes_for != null || p.vote_summary)" class="sn-vote-bar-section">
                <div class="sn-vote-counts">
                  <span class="sn-vote-count sn-vote-count--for">{{ t('senateView.governance.for') }}: {{ fedVotes(p).f }}</span>
                  <span class="sn-vote-count sn-vote-count--against">{{ t('senateView.governance.against') }}: {{ fedVotes(p).a }}</span>
                </div>
                <div class="sn-vote-bar-track">
                  <div class="sn-vote-bar-fill sn-vote-bar-fill--for" :style="{ width: fedVotes(p).fPct + '%' }"></div>
                  <div class="sn-vote-bar-fill sn-vote-bar-fill--against" :style="{ width: fedVotes(p).aPct + '%', left: fedVotes(p).fPct + '%' }"></div>
                </div>
              </div>

              <!-- Multi-registry + veto info -->
              <div style="display: flex; gap: 12px; flex-wrap: wrap; margin-top: 8px; font-size: 0.78rem;">
                <span v-if="p.distinct_registries || p.vote_summary?.distinct_registries" class="sn-fed-registries">
                  {{ t('senateView.federation.registriesVoted', { n: p.vote_summary?.distinct_registries || p.distinct_registries || 0 }) }}
                </span>
                <span v-if="p.status === 'PASSED' && p.veto_deadline" class="sn-fed-veto-timer">
                  {{ t('senateView.federation.vetoWindow') }}: {{ dayjs(p.veto_deadline).fromNow() }}
                </span>
                <span v-if="p.pass_rate != null" style="color: var(--muted);">
                  {{ t('senateView.federation.passRate') }}: {{ p.pass_rate }}%
                </span>
              </div>

              <!-- Policy diff preview -->
              <div v-if="p.policy_diff" class="sn-fed-policy-diff">
                <pre>{{ JSON.stringify(p.policy_diff, null, 2) }}</pre>
              </div>

              <FederationBallotPanel v-if="p.ballot_mode" :proposal-id="String(p.id)" :status="p.status" :end-timestamp="p.end_timestamp ?? null"
                :summary="p.ballot_summary ?? null" host-key="self" :host-name="ballotSelfName" :hosted="true"
                :open="selfOpenById.get(String(p.id)) || null" :hosts="ballotHosts" :my-registry-id="myRegistryId"
                :is-admin="authStore.isAdmin" :has-members="hasMembers" :min-registries="p.min_registries ?? null"
                @changed="fetchFederationProposals" @open-local="openLocalVote" />

              <!-- Actions -->
              <div style="display: flex; gap: 8px; margin-top: 12px;">
                <button v-if="p.status === 'VOTING' && !p.ballot_mode" class="sn-cta-btn" style="font-size: 0.78rem; padding: 6px 14px;"
                  @click="selectedFedProposal = p; showFedVoteModal = true; fedVoteReason = ''">
                  {{ t('senateView.governance.vote') }}
                </button>
                <button v-if="p.status === 'PASSED' && authStore.isAdmin" class="sn-ghost-btn" style="font-size: 0.78rem; padding: 6px 14px; border-color: #ef4444; color: #ef4444;"
                  @click="selectedFedProposal = p; showFedVetoModal = true; fedVetoReason = ''">
                  {{ t('senateView.federation.veto') }}
                </button>
              </div>
            </div>
          </div>
        </template>
      </div><!-- /federation tab -->

      <!-- §MEMBERSHIP phase C: the commons (a season's budget pays work members point to), where the registry runs it -->
      <div v-if="activeTab === 'commons' && commonsOn" class="sn-tab-content">
        <CommonsPanel />
      </div>

    </template><!-- /not loading -->

    <!-- ── Federation Vote Modal ─────────────────────────────────────────── -->
    <Teleport to="body">
      <div v-if="showFedVoteModal && selectedFedProposal" class="sn-modal-overlay" @click.self="showFedVoteModal = false">
        <div class="sn-modal" role="dialog" aria-modal="true" aria-labelledby="sn-fedvote-title">
          <h3 id="sn-fedvote-title" class="sn-modal__title">{{ t('senateView.voteModal.title') }}</h3>
          <p class="sn-modal__sub">{{ selectedFedProposal.title }}</p>
          <p style="font-size: 0.78rem; color: var(--muted); margin-bottom: 12px;">{{ t('senateView.voteModal.by') }} {{ selectedFedProposal.proposer_operator_name }}</p>
          <textarea v-model="fedVoteReason" :placeholder="t('senateView.voteModal.reasonHint')" rows="2"
            style="width: 100%; background: rgba(0,0,0,0.3); border: 1px solid var(--border); border-radius: 6px; padding: 10px; color: var(--text); font-family: inherit; font-size: 0.85rem; resize: none; margin-bottom: 12px;"></textarea>
          <div style="display: flex; gap: 8px; justify-content: flex-end;">
            <button class="sn-ghost-btn" @click="showFedVoteModal = false">{{ t('common.cancel') }}</button>
            <button class="sn-ghost-btn" style="border-color: #ef4444; color: #ef4444;" :disabled="isActing" @click="submitFedVote(false)">{{ t('senateView.voteModal.voteAgainst') }}</button>
            <button class="sn-cta-btn" :disabled="isActing" @click="submitFedVote(true)">{{ isActing ? t('senateView.voteModal.voting') : t('senateView.voteModal.voteFor') }}</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ── Federation Veto Modal ─────────────────────────────────────────── -->
    <Teleport to="body">
      <div v-if="showFedVetoModal && selectedFedProposal" class="sn-modal-overlay" @click.self="showFedVetoModal = false">
        <div class="sn-modal" role="dialog" aria-modal="true" aria-labelledby="sn-fedveto-title">
          <h3 id="sn-fedveto-title" class="sn-modal__title">{{ t('senateView.vetoModal.title') }}</h3>
          <p class="sn-modal__sub">{{ selectedFedProposal.title }}</p>
          <p style="font-size: 0.82rem; color: #ef4444; margin-bottom: 12px;">{{ t('senateView.vetoModal.warning') }}</p>
          <textarea v-model="fedVetoReason" :placeholder="t('senateView.vetoModal.reasonHint')" rows="3" required
            style="width: 100%; background: rgba(0,0,0,0.3); border: 1px solid var(--border); border-radius: 6px; padding: 10px; color: var(--text); font-family: inherit; font-size: 0.85rem; resize: none; margin-bottom: 12px;"></textarea>
          <div style="display: flex; gap: 8px; justify-content: flex-end;">
            <button class="sn-ghost-btn" @click="showFedVetoModal = false">{{ t('common.cancel') }}</button>
            <button class="sn-cta-btn" style="background: rgba(239,68,68,0.15); border-color: #ef4444; color: #ef4444;" :disabled="isActing || !fedVetoReason" @click="submitFedVeto()">{{ isActing ? t('senateView.vetoModal.vetoing') : t('senateView.vetoModal.confirm') }}</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ── Modals ──────────────────────────────────────────────────────────── -->
    <StakeModal
      v-model:show="showStakeModal"
      :teg-balance="tegStore.balance"
      :tiers="senateStakeTiers"
      :rates-on="senateRatesOn"
      :loading="isActing"
      @stake="handleStake"
    />
    <UnstakeModal
      v-model:show="showUnstakeModal"
      :position="selectedPosition"
      :rates-on="senateRatesOn"
      :loading="isActing"
      @confirm="confirmUnstake"
    />
    <VoteModal
      v-model:show="showVoteModal"
      :proposal="selectedProposal"
      :voting-power="governanceStore.myVotingPower"
      :loading="isActing"
      :member-mode="memberMode"
      :member-weight="memberWeightText"
      @vote="submitVote"
    />
    <StepUpConfirm
      v-if="stepUp"
      :show="!!stepUp"
      :challenge="stepUp"
      :busy="isActing"
      :error="stepUpError"
      @update:show="(v: boolean) => { if (!v) cancelStepUp() }"
      @approved="(id: string) => castAsMember({ challengeId: id })"
      @code="(code: string) => castAsMember({ totpCode: code })"
    />
    <CreateProposalModal
      v-model:show="showProposalModal"
      :loading="isActing"
      @create="createProposal"
    />

    </div><!-- /sn-content -->
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { fmtCount } from '@/services/cockpit/num'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { ref, computed, nextTick, onMounted, watch } from 'vue'
import { useEscapeClose } from '@/composables/useEscapeClose'
import { useRoute } from 'vue-router'
import { loadRegistryConfig, useRegistryConfig } from '@/composables/useRegistryConfig'
import { lockOnlyTiers } from '@/services/stakingLocks'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import { useStakingStore } from '@/stores/staking'
import { useGovernanceStore } from '@/stores/governance'
import { useTegStore } from '@/stores/teg'
import { useUIStore } from '@/stores/ui'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/composables/useI18n'
import { useCurrency } from '@/composables/useCurrency'
import { apiClient } from '@/services/api/client'
import { failureReason, proposalUnit, quorumMarkerLeft, requiredPower, storedQuorumRequired } from '@/services/governanceQuorum'
import StakeModal          from '@/components/senate/StakeModal.vue'
import UnstakeModal        from '@/components/senate/UnstakeModal.vue'
import VoteModal           from '@/components/senate/VoteModal.vue'
import CreateProposalModal from '@/components/senate/CreateProposalModal.vue'
import MembershipPanel     from '@/components/membership/MembershipPanel.vue'
import StepUpConfirm       from '@/components/membership/StepUpConfirm.vue'
import CommonsPanel        from '@/components/commons/CommonsPanel.vue'
import VotePermissionNotice from '@/components/membership/VotePermissionNotice.vue'
import FederationBallotPanel from '@/components/governance/FederationBallotPanel.vue'
import { fetchOpenBallots, fedStatusPill, raisedBy, type BallotSummary, type OpenBallotProposal, type OpenBallotsDoc } from '@/services/governance/federationBallots'
import { useMembership } from '@/composables/useMembership'
import { commonsEnabled, governanceMode, memberVoteFigure, weightLabel, type StepUpChallenge } from '@/services/membership/membership'
import { lockSentence, stakingOpen, stakingTabShown } from '@/services/membership/stakingTab'
import type { MemberVoteOutcome } from '@/services/api/governance'
import '@/components/senate/tp-senate.css'

dayjs.extend(relativeTime)

// #2 (2026-05-08): typed shapes. Defined locally rather than in @/types
// because the data here is normalized inside multiple stores (locking,
// governance) — backends return slightly different envelopes per endpoint
// and the views deal with the union surface.
interface ApiErrorLike {
  response?: { data?: { detail?: string; message?: string } }
  message?: string
}
function errorMessage(e: unknown, fallback?: string): string {
  const err = e as ApiErrorLike
  return err?.response?.data?.detail || err?.response?.data?.message || err?.message || fallback || t('senateView.toast.actionFailed', 'Action failed')
}

interface StakingPosition {
  id: string
  amount: string
  apy?: number | string
  lockPeriod: number
  lock_period?: number
  startDate?: string
  staked_at?: string
  unlockDate?: string | null
  rewards?: string | { earned?: string; claimed?: string; available?: string }
  rewards_earned?: string
  status?: string
  canUnstake?: boolean
}

interface ApyTier {
  lockPeriod: number
  apy: number
  baseApy?: number
  lockPremium?: number
  minAmount?: string
  label?: string
  description?: string
}

interface Proposal {
  id: string | number
  proposal_id?: string | number
  title: string
  description?: string
  proposal_type?: string
  status?: string
  votes_for?: number | string
  votes_against?: number | string
  votes_abstain?: number | string
  total_voting_power?: number | string
  quorum_required?: number | string
  quorumPercent?: number | null  // the quorum this proposal's tally applies (null: none stored)
  // the numbers a decided proposal was decided on (services/api/governance.ts; null: open, or tallied before 0185)
  tallyWeightMode?: 'lock' | 'member' | null
  tallyQuorumRequired?: number | null
  tallyQuorumMet?: boolean | null
  voting_ends_at?: string
  end_time?: string
  created_at?: string
  policy_diff?: Record<string, unknown>
}

interface FederationProposal extends Proposal {
  vote_in_favor?: boolean
  veto_reason?: string
  proposing_registry_id?: string
  target_registry_id?: string
  // the store's own fields (agentvault-event-store services/federation_governance.py::_proposal_to_dict)
  proposer_operator_name?: string
  origin_registry_id?: string
  origin_proposal_id?: number | null
  end_timestamp?: string
  veto_deadline?: string | null
  distinct_registries?: number | null
  pass_rate?: number | null
  vote_summary?: { votes_for?: number; votes_against?: number; distinct_registries?: number } | null
  // §MEMBERSHIP D2: decided by one ballot per registry, and the count once it is decided
  ballot_mode?: boolean
  ballot_summary?: BallotSummary | null
  min_registries?: number | null
}

interface FundingRequest {
  id: string | number
  agent_did?: string
  amount?: string | number
  reason?: string
  status?: string
  requested_at?: string
  developer_id?: number | string
  approved_amount?: string | number
}

const stakingStore    = useStakingStore()
const governanceStore = useGovernanceStore()
const tegStore        = useTegStore()
/* §FESUITE: every outcome on this floor went to realtimeStore.addActivity, a feed no component renders: 18 sentences
   (proposal created or refused, vote cast or refused, locked, tallied, "policy NOT applied") nobody ever saw. They are
   toasts now, and a refusal carries the server's reason (errorMessage) instead of "Request failed with status code 403". */
function notify(a: { type: 'success' | 'error' | 'warning' | 'info'; title: string; message?: string }) {
  if (a.type === 'error') uiStore.showError(a.title, a.message)
  else if (a.type === 'warning') uiStore.showWarning(a.title, a.message)
  else if (a.type === 'info') uiStore.showInfo(a.title, a.message)
  else uiStore.showSuccess(a.title, a.message)
}
const uiStore         = useUIStore()
const authStore       = useAuthStore()
const { t, tp }        = useI18n()
// FX multi-currency: staking/funding amounts are this registry's currency (AVT/BVT).
const { localCurrency } = useCurrency()

// ── State ──────────────────────────────────────────────────────────────────
const activeTab        = ref<'staking' | 'governance' | 'funding' | 'federation' | 'commons'>('staking')
/* §FESUITE: a link can open a tab (?tab=governance), on arrival and when the view is already mounted (a query-only
   navigation reuses the component, so onMounted alone would miss the second arrival). */
const senateRoute = useRoute()
function applyTabQuery() {
  const q = String(senateRoute.query.tab || '')
  if (q === 'staking' || q === 'governance' || q === 'federation') activeTab.value = q
  else if (q === 'funding' && authStore.isAdmin) activeTab.value = q
  else if (q === 'commons') activeTab.value = q   // shown once the registry's config says the commons is on
}
watch(() => senateRoute.query.tab, applyTabQuery, { immediate: true })
const isLoading        = ref(true)
const stakingLoading   = ref(true)
const governanceLoading = ref(true)
const isActing         = ref(false)
const proposalFilter   = ref('all')

const showStakeModal    = ref(false)
// §BAFIN (2026-10-01): the Senate opens no lock door where the registry switched locking off, and shows no
// rate where payouts on locked units are off (core/staking_gate.py, read through /public/registry-config).
const { config: senateRegistryCfg, loaded: senateRegistryCfgLoaded } = useRegistryConfig()
// §MEMBERSHIP (V0564): fail-closed like the rates below; `!== false` opened the door while the config was in flight.
const senateStakingOn = computed(() => stakingOpen(senateRegistryCfg.value))
// §BAFIN B.5.5 (agentvault2-5b, 2026-10-03): fail-closed. No rate or payout figure shows until the registry has
// said payouts are on; `!== false` showed one while the config was in flight and kept it if the read failed.
const senateRatesOn = computed(() => senateRegistryCfg.value.staking_rewards_enabled === true)
// §MEMBERSHIP (2026-10-02): where the registry runs member mode a vote is one per member, weighted by tenure, and a
// binding vote may need a step-up; the lock breakdown means nothing there. Absent (every registry before the
// membership image) is today's lock mode, and this page renders exactly as before.
const memberMode = computed(() => governanceMode(senateRegistryCfg.value) === 'member')
// §MEMBERSHIP phase C: the commons tab exists only where the registry runs the commons (COMMONS_ENABLED); a link to it
// on a registry without one lands on Governance instead of an empty tab.
const commonsOn = computed(() => commonsEnabled(senateRegistryCfg.value))
watch([commonsOn, senateRegistryCfgLoaded], ([on, loaded]) => {
  if (loaded && !on && activeTab.value === 'commons') activeTab.value = 'governance'
}, { immediate: true })
// §MEMBERSHIP (V0564): the Locks tab exists where new positions open, or where the person still holds positions to
// unlock (services/membership/stakingTab.ts). Locks is the DEFAULT tab, so where it does not exist the page, and a
// link with ?tab=staking, land on Governance once the config and the person's positions have been read.
const stakingTabVisible = computed(() => stakingTabShown(senateRegistryCfg.value, stakingStore.activePositions.length))
const stakingDecided = computed(() => senateRegistryCfgLoaded.value && !stakingLoading.value)
watch([stakingTabVisible, stakingDecided], ([shown, decided]) => {
  if (decided && !shown && activeTab.value === 'staking') activeTab.value = 'governance'
}, { immediate: true })
const { me: membership, stats: membershipStats, load: loadMembership, reload: reloadMembership } = useMembership()
const memberWeightText = computed(() => membership.value?.is_member
  ? weightLabel(membership.value.weight, appLocale())
  : t('membership.senate.notMemberValue', 'not a member'))
watch(memberMode, (on) => { if (on) void loadMembership() }, { immediate: true })
// a template-called factory would hand the modal a fresh array on every render; build the fallback once
const SENATE_LOCK_ONLY = lockOnlyTiers()
const senateStakeTiers = computed(() => (stakingStore.apyTiers.length ? stakingStore.apyTiers : SENATE_LOCK_ONLY))
const showUnstakeModal  = ref(false)
const showVoteModal     = ref(false)
const showProposalModal = ref(false)
const selectedPosition  = ref<StakingPosition | null>(null)
const selectedProposal  = ref<Proposal | null>(null)
const stakingPositionsLimit = ref(20)

// ── Federation Governance ────────────────────────────────────────────────
const federationProposals = ref<FederationProposal[]>([])
const federationLoading = ref(false)
const federationFilter = ref('all')
const showFedVoteModal = ref(false)
const selectedFedProposal = ref<FederationProposal | null>(null)
const fedVoteReason = ref('')
const fedVetoReason = ref('')
const showFedVetoModal = ref(false)
// §COCKPITDESK (2026-10-15): the federation vote and veto dialogs close on Escape wherever the focus is, never while they submit
useEscapeClose(() => showFedVoteModal.value && !!selectedFedProposal.value, () => { showFedVoteModal.value = false }, () => !isActing.value)
useEscapeClose(() => showFedVetoModal.value && !!selectedFedProposal.value, () => { showFedVetoModal.value = false }, () => !isActing.value)
/* §MCPTEST30 (V0557): federal ballots (§MEMBERSHIP D2) on this floor. Where this registry runs ballot mode, the open
   ballot proposals here and at its frame peers are read beside the proposals; a ballot proposal then shows its ballots
   and this registry's next step instead of an agent's vote bar, and the proposals other registries host get a section
   of their own (a peer's proposal lives in the peer's store, not in this registry's list). Ballot mode off (production
   until his word): nothing new is read or shown. */
const ballotModeHere = computed(() => senateRegistryCfg.value.federation_ballot_mode === true)
const ballotDoc = ref<OpenBallotsDoc | null>(null)
const ballotHosts = computed(() => ballotDoc.value?.hosts ?? [])
const ballotSelfName = computed(() => ballotHosts.value.find(h => h.host === 'self')?.name ?? '')
const myRegistryId = computed(() => ballotDoc.value?.registry_id ?? '')
const selfOpenById = computed(() => {
  const m = new Map<string, OpenBallotProposal>()
  for (const h of ballotHosts.value) if (h.host === 'self') for (const p of h.proposals || []) m.set(String(p.id), p)
  return m
})
const peerOpen = computed(() => ballotHosts.value.filter(h => h.host !== 'self')
  .flatMap(h => (h.proposals || []).map(p => ({ host: h, proposal: p }))))
const peerBallotErrors = computed(() => ballotHosts.value.filter(h => h.host !== 'self' && h.error))
// the routes decide by the same rule: members only where the registry weighs members AND has some. null while the
// membership read has not answered in member mode: the panel then offers no door (agentvault2-0f's review)
const hasMembers = computed<boolean | null>(() => !memberMode.value ? false
  : membershipStats.value ? Number(membershipStats.value.members ?? 0) > 0 : null)
function fedRaisedBy(p: FederationProposal): string {
  return raisedBy(p, ballotHosts.value) || p.proposer_operator_name || ''
}
// belt and braces: the switch turning on after a list was read without it reads the list again
// one read at a time: the switch can arrive while the first read still awaits the config (agentvault2-0f's review)
let fedFetching = 0
watch(ballotModeHere, (on) => { if (on && !ballotDoc.value && !fedFetching) void fetchFederationProposals() })
async function openLocalVote(id: number) {
  activeTab.value = 'governance'
  await governanceStore.fetchProposals()
  await nextTick()
  document.querySelector(`[data-id="${id}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

// §FESUITE (V0576): a failed read is not "none": the person's lock positions (and the two figures beside them), the
// federation proposals and the admin's funding queue each say their read failed, with Try again
const stakingReadFailed = ref(false)
// the ledger's total answered and the positions did not: the list is unread, not empty (a zero total has no positions)
const positionsUnread = computed(() => !stakingStore.positionsReadable && Number(stakingStore.totalStaked) > 0)
const fedFailed = ref(false)
const fundingFailed = ref(false)
function readMyStaking() {
  return stakingStore.fetchMyStakingStats().then(() => { stakingReadFailed.value = false }, (e) => { stakingReadFailed.value = true; throw e })
}

async function fetchFederationProposals() {
  fedFetching++
  federationLoading.value = true
  try {
    // the switch is read from the registry's config: on a cold arrival (a link, a slow first answer) it can answer after
    // the floor mounts, and a list read before it would never be read again (agentvault2-0f's review)
    if (!senateRegistryCfgLoaded.value) await loadRegistryConfig().catch(() => undefined)
    const ballots = ballotModeHere.value ? fetchOpenBallots().catch(() => null) : Promise.resolve(null)
    const { data } = await apiClient.get('/governance/federation/proposals')
    federationProposals.value = Array.isArray(data) ? data : []
    fedFailed.value = false
    ballotDoc.value = await ballots
  } catch (e: unknown) {
    console.error('[Federation] Failed to fetch proposals:', e)
    fedFailed.value = true
  } finally {
    federationLoading.value = false
    fedFetching--
  }
}

async function submitFedVote(inFavor: boolean) {
  if (!selectedFedProposal.value) return
  isActing.value = true
  try {
    await apiClient.post(`/governance/federation/proposals/${selectedFedProposal.value.id}/vote`, {
      vote_in_favor: inFavor,
      reason: fedVoteReason.value || undefined,
    }, memberMode.value ? { expectedStatuses: [409] } : undefined)
    showFedVoteModal.value = false
    selectedFedProposal.value = null
    fedVoteReason.value = ''
    notify({ type: 'success', title: t('senateView.toast.fedVoteCast', 'Federation Vote Cast'),
      message: inFavor ? t('senateView.toast.fedVotedFor', 'Voted FOR on federation proposal') : t('senateView.toast.fedVotedAgainst', 'Voted AGAINST on federation proposal') })
    await fetchFederationProposals()
  } catch (e: unknown) {
    const fe = e as { response?: { status?: number; data?: { error?: string } } }
    if (fe?.response?.status === 409 && fe.response.data?.error === 'registry_ballots') {
      showFedVoteModal.value = false
      notify({ type: 'info', title: t('senateView.federation.ballots.registryDecides', 'Registries decide this one'),
        message: t('senateView.federation.ballots.registryDecidesMsg', "Federation proposals here are decided by one ballot per registry. With members, the registry's ballot follows their vote on the linked local proposal; vote there.") })
      return
    }
    if (memberMode.value && fe?.response?.status === 409 && fe.response.data?.error === 'federation_ballot_pending') {
      showFedVoteModal.value = false
      notify({ type: 'info', title: t('membership.vote.federationPending', 'Registry ballots come later'),
        message: t('membership.vote.federationPendingMsg', 'On this registry, federation proposals are decided by one ballot per registry. That vote opens with the next step of the rollout.') })
      return
    }
    notify({ type: 'error', title: t('senateView.toast.voteFailed', 'Vote Failed'), message: errorMessage(e, t('senateView.toast.fedVoteFailedMsg', 'Failed to cast federation vote')) })
  } finally {
    isActing.value = false
  }
}

async function submitFedVeto() {
  if (!selectedFedProposal.value || !fedVetoReason.value) return
  isActing.value = true
  try {
    await apiClient.post(`/governance/federation/proposals/${selectedFedProposal.value.id}/veto`, {
      reason: fedVetoReason.value,
    })
    showFedVetoModal.value = false
    selectedFedProposal.value = null
    fedVetoReason.value = ''
    notify({ type: 'success', title: t('senateView.toast.vetoed', 'Proposal Vetoed'), message: t('senateView.toast.vetoedMsg', 'Federation proposal vetoed') })
    await fetchFederationProposals()
  } catch (e: unknown) {
    notify({ type: 'error', title: t('senateView.toast.vetoFailed', 'Veto Failed'), message: errorMessage(e) })
  } finally {
    isActing.value = false
  }
}

const filteredFedProposals = computed(() => {
  if (federationFilter.value === 'all') return federationProposals.value
  return federationProposals.value.filter(p => p.status?.toUpperCase() === federationFilter.value.toUpperCase())
})

const fedStats = computed(() => ({
  total: federationProposals.value.length,
  voting: federationProposals.value.filter(p => p.status === 'VOTING').length,
  passed: federationProposals.value.filter(p => p.status === 'PASSED' || p.status === 'APPLIED').length,
  vetoed: federationProposals.value.filter(p => p.status === 'VETOED').length,
}))

function fedStatusClass(status: string): string {
  const s = status?.toUpperCase()
  if (s === 'VOTING') return 'sn-proposal-card--active'
  if (s === 'PASSED' || s === 'APPLIED') return 'sn-proposal-card--passed'
  if (s === 'FAILED') return 'sn-proposal-card--failed'
  if (s === 'VETOED') return 'sn-proposal-card--failed'
  return ''
}

function fedStatusLabel(status: string): string {
  const s = status?.toUpperCase()
  if (s === 'VOTING') return t('senateView.federation.ballots.statusVoting', 'Voting')
  if (s === 'PASSED') return t('senateView.federation.ballots.statusPassed', 'Passed')
  if (s === 'APPLIED') return t('senateView.federation.ballots.statusApplied', 'Applied')
  if (s === 'FAILED') return t('senateView.federation.ballots.statusFailed', 'Failed')
  if (s === 'VETOED') return t('senateView.federation.ballots.statusVetoed', 'Vetoed')
  return status || t('senateView.federation.ballots.statusUnknown', 'Unknown')
}

// §MCPTEST30 (V0558): an older (non-ballot) federation proposal's votes, read once for the counts and the bar
function fedVotes(p: FederationProposal): { f: number; a: number; fPct: number; aPct: number } {
  const f = Number(p.vote_summary?.votes_for ?? p.votes_for ?? 0) || 0
  const a = Number(p.vote_summary?.votes_against ?? p.votes_against ?? 0) || 0
  const n = f + a
  return { f, a, fPct: n ? (f / n) * 100 : 0, aPct: n ? (a / n) * 100 : 0 }
}

// ── Auto-Tally Config ────────────────────────────────────────────────────
const autoTallyConfig = ref<{ enabled: boolean; interval_seconds: number; source: string }>({ enabled: true, interval_seconds: 60, source: 'env' })
const autoTallyInterval = ref<number>(60)

// SF2+SF3 (audit 2026-05-07): apiClient interceptor already injects the dev
// token for these dev-tier endpoints — manual Authorization headers were
// redundant + raced against the auth-store on logout. Removed.
async function fetchAutoTallyConfig() {
  try {
    const { data } = await apiClient.get('/governance/auto-tally/config')
    autoTallyConfig.value = data
    autoTallyInterval.value = data.interval_seconds || 60
  } catch { /* expected */ }
}

async function toggleAutoTally() {
  try {
    const { data } = await apiClient.put('/governance/auto-tally/config', { enabled: !autoTallyConfig.value.enabled })
    autoTallyConfig.value = data
    uiStore.showSuccess(t('senateView.toast.autoTallyUpdated', 'Auto-Tally Updated'),
      data.enabled ? t('senateView.toast.autoTallyEnabled', 'Auto-tally enabled.') : t('senateView.toast.autoTallyDisabled', 'Auto-tally disabled.'))
  } catch (e: unknown) {
    console.error('Failed to toggle auto-tally:', e)
    uiStore.showError(t('senateView.toast.autoTallyFailed', 'Auto-Tally Failed'), (e as ApiErrorLike)?.response?.data?.detail || t('senateView.toast.autoTallyFailedMsg', 'Could not update auto-tally setting.'))
  }
}

async function updateAutoTallyInterval() {
  try {
    const { data } = await apiClient.put('/governance/auto-tally/config', { interval_seconds: autoTallyInterval.value })
    autoTallyConfig.value = data
    uiStore.showSuccess(t('senateView.toast.intervalUpdated', 'Interval Updated'), tp('senateView.toast.intervalSet', 'Auto-tally interval set to {s}s.', { s: data.interval_seconds }))
  } catch (e: unknown) {
    console.error('Failed to update auto-tally interval:', e)
    uiStore.showError(t('senateView.toast.intervalFailed', 'Interval Update Failed'), (e as ApiErrorLike)?.response?.data?.detail || t('senateView.toast.intervalFailedMsg', 'Could not update auto-tally interval.'))
  }
}

// ── Funding Admin State ──────────────────────────────────────────────────
const fundingRequests    = ref<any[]>([])
const fundingLoading     = ref(false)
const fundingActing      = ref(false)
const approveInputId     = ref<string | null>(null)
const approveAmount      = ref<number>(0)
const rejectInputId      = ref<string | null>(null)
const rejectReason       = ref('')

const pendingFundingRequests = computed(() => fundingRequests.value.filter(r => r.status?.toLowerCase() === 'pending'))
const pastFundingRequests = computed(() => fundingRequests.value.filter(r => r.status?.toLowerCase() !== 'pending'))
const totalPendingAVT = computed(() => pendingFundingRequests.value.reduce((s, r) => s + Number(r.requested_amount || r.amount || 0), 0))
const totalApprovedAVT = computed(() => fundingRequests.value.filter(r => r.status?.toLowerCase() === 'approved').reduce((s, r) => s + Number(r.approved_amount || r.requested_amount || 0), 0))
const totalFundedAVT = computed(() => fundingRequests.value.filter(r => r.status?.toLowerCase() === 'funded').reduce((s, r) => s + Number(r.approved_amount || r.requested_amount || 0), 0))

async function fetchFundingRequests() {
  if (!authStore.isAdmin) return
  fundingLoading.value = true
  try {
    // SF2+SF3 (audit 2026-05-07): apiClient interceptor handles dev-token
    // injection for /admin/* — no manual header needed.
    const { data } = await apiClient.get('/admin/funding/all')
    fundingRequests.value = Array.isArray(data) ? data : (data.requests || [])
    fundingFailed.value = false
  } catch (e: unknown) {
    console.error('Failed to fetch funding requests:', e)
    fundingRequests.value = []
    fundingFailed.value = true
    uiStore.showWarning(t('senateView.toast.fundingRequests', 'Funding Requests'), t('senateView.toast.fundingLoadFailed', 'Could not load funding requests.'))
  } finally {
    fundingLoading.value = false
  }
}

function openApproveInput(req: FundingRequest) {
  approveInputId.value = req.id
  approveAmount.value = Number(req.requested_amount || req.amount) || 0
  rejectInputId.value = null
}

function openRejectInput(req: FundingRequest) {
  rejectInputId.value = req.id
  rejectReason.value = ''
  approveInputId.value = null
}

async function approveFundingRequest(reqId: string) {
  if (!authStore.isAdmin) return
  fundingActing.value = true
  try {
    // SF2+SF3 (audit 2026-05-07): apiClient interceptor injects dev token.
    await apiClient.post(`/admin/funding/${reqId}/approve`, {
      approved_amount: String(approveAmount.value)
    })
    uiStore.showSuccess(t('senateView.toast.approved', 'Approved'), t('senateView.toast.approvedMsg', 'Funding request approved'))
    approveInputId.value = null
    await fetchFundingRequests()
  } catch (e: unknown) {
    uiStore.showError(t('senateView.toast.approveFailed', 'Approve Failed'), errorMessage(e, t('senateView.toast.approveFailedMsg', 'Failed to approve')))
  } finally {
    fundingActing.value = false
  }
}

async function rejectFundingRequest(reqId: string) {
  if (!authStore.isAdmin) return
  fundingActing.value = true
  try {
    // SF2+SF3 (audit 2026-05-07): apiClient interceptor injects dev token.
    await apiClient.post(`/admin/funding/${reqId}/reject`, {
      reason: rejectReason.value.trim() || 'Request denied by administrator'
    })
    uiStore.showSuccess(t('senateView.toast.rejected', 'Rejected'), t('senateView.toast.rejectedMsg', 'Funding request rejected'))
    rejectInputId.value = null
    await fetchFundingRequests()
  } catch (e: unknown) {
    uiStore.showError(t('senateView.toast.rejectFailed', 'Reject Failed'), errorMessage(e, t('senateView.toast.rejectFailedMsg', 'Failed to reject')))
  } finally {
    fundingActing.value = false
  }
}

function fundingStatusColor(status: string): string {
  switch (status?.toLowerCase()) {
    case 'pending': return 'rgb(251,191,36)'
    case 'approved': return 'var(--sn-cyan)'  /* §2026-06-07 was blue rgb(59,130,246) — off-theme; now theme-reactive primary */
    case 'funded': return 'rgb(34,197,94)'
    case 'rejected': return 'rgb(239,68,68)'
    default: return 'rgb(148,163,184)'
  }
}

function fundingShortDid(did?: string) {
  if (!did) return 'Unknown'
  if (did.length <= 24) return did
  return did.slice(0, 16) + '...' + did.slice(-6)
}

function fundingFormatDate(iso: string): string {
  if (!iso) return '--'
  return dayjs(iso).format('MMM D, YYYY')
}

// ── Init ──────────────────────────────────────────────────────────────────
onMounted(async () => {
  isLoading.value = true
  stakingLoading.value = true
  governanceLoading.value = true

  // Load locking and governance in parallel, but track each independently
  // so the page can render as soon as any tab's data is ready
  const stakingFetch = Promise.all([
    readMyStaking(),
    stakingStore.fetchGlobalStats(),
    stakingStore.fetchApyTiers(),
    tegStore.fetchBalance()
  ]).catch(e => {
    console.error('Staking data load failed:', e)
    uiStore.showWarning(t('senateView.toast.stakingUnavailable', 'Lock Data Unavailable'), t('senateView.toast.stakingUnavailableMsg', 'Could not load lock information. Some features may be limited.'))
  }).finally(() => {
    stakingLoading.value = false
  })

  const govFetch = Promise.all([
    governanceStore.fetchProposals(),
    governanceStore.fetchVotingPower(),
    governanceStore.fetchStats()
  ]).catch(e => {
    console.error('Governance data load failed:', e)
    uiStore.showWarning(t('senateView.toast.governanceUnavailable', 'Governance Data Unavailable'), t('senateView.toast.governanceUnavailableMsg', 'Could not load proposal data. Please try refreshing.'))
  }).finally(() => {
    governanceLoading.value = false
  })

  // Fire-and-forget admin data
  if (authStore.isAdmin) {
    fetchFundingRequests()
    fetchAutoTallyConfig()
  }

  // Fire-and-forget federation data
  fetchFederationProposals()

  // Wait for at least the active tab's data before removing global spinner
  try {
    // Wait for both, but the global spinner clears once the first finishes
    await Promise.race([stakingFetch, govFetch])
  } catch { /* expected */ }
  isLoading.value = false

  // Ensure both complete in background
  await Promise.all([stakingFetch, govFetch]).catch(() => {})
})

// ── Computed ──────────────────────────────────────────────────────────────
const visiblePositions = computed(() => {
  const all = stakingStore.activePositions
  return all.slice(0, stakingPositionsLimit.value)
})

const hasMorePositions = computed(() =>
  stakingStore.activePositions.length > stakingPositionsLimit.value
)

const activeProposalsCount = computed(() =>
  governanceStore.proposals.filter(p =>
    p.status?.toLowerCase() === 'voting' || p.status?.toLowerCase() === 'active'
  ).length
)

const proposalFilters = computed(() => {
  const all = governanceStore.proposals
  return [
    { id: 'all',    label: 'All',    count: all.length },
    { id: 'active', label: 'Active', count: all.filter(p => isVotingActive(p)).length },
    { id: 'passed', label: 'Passed', count: all.filter(p => p.status?.toLowerCase() === 'passed').length },
    { id: 'ended',  label: 'Ended',  count: all.filter(p => proposalStatus(p) === 'Ended').length },
  ]
})

const filteredProposals = computed(() => {
  const all = governanceStore.proposals
  if (proposalFilter.value === 'all')    return all
  if (proposalFilter.value === 'active') return all.filter(p => isVotingActive(p))
  if (proposalFilter.value === 'passed') return all.filter(p => p.status?.toLowerCase() === 'passed')
  if (proposalFilter.value === 'ended')  return all.filter(p => proposalStatus(p) === 'Ended')
  return all
})

// ── Helpers ───────────────────────────────────────────────────────────────
function formatNum(v: string | number | null | undefined) {
  const n = parseFloat(String(v ?? '0'))
  if (isNaN(n)) return '0.00'
  return n.toLocaleString(appLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
function timeAgo(d?: string) { return d ? dayjs(d).fromNow() : '—' }
function getRemainingTime(d?: string) { return d ? dayjs(d).fromNow() : '—' }
function truncate(s: string, n: number) { return s?.length > n ? s.slice(0, n) + '…' : s }
function shortDid(did?: string) {
  if (!did) return 'Unknown'
  const core = did.replace('did:cos:', '')
  return 'did:co…' + core.slice(-4)
}
function lockedFor(unlockDate?: string) {
  if (!unlockDate) return '—'
  const diff = dayjs(unlockDate).diff(dayjs())
  if (diff <= 0) return 'now'
  const days  = Math.floor(diff / 86400000)
  const hours = Math.floor((diff % 86400000) / 3600000)
  return days > 0 ? `${days}d` : `${hours}h`
}
function posRewards(pos: StakingPosition) {
  const r = pos.rewards
  if (!r) return '0'
  if (typeof r === 'object') return r.earned || r.available || '0'
  return r
}

// ── Position card class ───────────────────────────────────────────────────
function posCardClass(pos: StakingPosition) {
  if (pos.canUnstake || pos.lockPeriod === 0) return 'sn-pos-card--ready'
  return 'sn-pos-card--locked'
}

// ── Proposal helpers ──────────────────────────────────────────────────────
function proposalStatus(p: Proposal) {
  const s = p.status?.toLowerCase()
  if (s === 'passed')  return 'Passed'
  if (s === 'failed' || s === 'rejected') return 'Failed'
  if (s === 'executed') return 'Executed'
  if (s === 'voting' || s === 'active') {
    const now = new Date(); const end = new Date(p.votingEnd || p.end_timestamp || p.endTime)
    if (now > end) return 'Ended'
    return 'Active'
  }
  return 'Pending'
}

function isVotingActive(p: Proposal) {
  return proposalStatus(p) === 'Active'
}

function proposalCardClass(p: Proposal) {
  const s = proposalStatus(p)
  if (s === 'Active')  return 'sn-proposal-card--active'
  if (s === 'Passed')  return 'sn-proposal-card--passed'
  if (s === 'Failed')  return 'sn-proposal-card--failed'
  if (s === 'Ended')   return 'sn-proposal-card--ended'
  return ''
}

function totalVotes(p: Proposal) {
  return parseFloat(p.votes?.for || p.votes_for || '0') +
         parseFloat(p.votes?.against || p.votes_against || '0')
}
function forPct(p: Proposal) {
  const f = parseFloat(p.votes?.for || p.votes_for || '0')
  const t = totalVotes(p)
  return t === 0 ? 0 : Math.round((f / t) * 100)
}
function againstPct(p: Proposal) {
  const a = parseFloat(p.votes?.against || p.votes_against || '0')
  const t = totalVotes(p)
  return t === 0 ? 0 : Math.round((a / t) * 100)
}
// §BATCH0911 item 2b — the quorum a proposal STORED is the one its tally applies; with none stored
// the tally applies none, so there is no line and no required figure (governanceQuorum.ts). These
// used to fall back to 10 and to a network power of 100, which matched one frame and described nothing.
function getQuorumDisplay(p: Proposal) {
  const cast = voteAmount(totalVotes(p), p)
  if (p.quorumPercent == null) return `${cast} / —`
  // a decided proposal shows the quorum it was decided on; an open one (or one tallied before that was stored) shows
  // the quorum as of now, which moves as the network changes
  const req = storedQuorumRequired(p) ?? requiredPower(governanceStore.networkVePower, p.quorumPercent)
  return `${cast} / ${req == null ? '—' : voteAmount(req, p)} (${p.quorumPercent}%)`
}
/** A vote figure as the floor speaks it, in the unit of the proposal's tally (or of the registry now): power in lock
 *  mode as before; weights in member mode, never points. */
function voteAmount(v: string | number | null | undefined, p?: Proposal) {
  const unit = p ? proposalUnit(p, memberMode.value) : (memberMode.value ? 'member' : 'lock')
  return unit === 'member' ? memberVoteFigure(v, membershipStats.value?.points_per_weight, appLocale()) : formatNum(v)
}

// ── Actions ───────────────────────────────────────────────────────────────
function openStakeWithTier(tier: ApyTier) {
  if (!senateStakingOn.value) return   // §MEMBERSHIP (V0564): no lock door where no new position opens
  showStakeModal.value = true
}

async function handleStake(amount: string, lockPeriod: number) {
  isActing.value = true
  try {
    await stakingStore.stake({ amount, lockPeriod })
    await Promise.all([readMyStaking(), tegStore.fetchBalance()])
    showStakeModal.value = false
    notify({ type: 'success', title: t('senateView.toast.staked', 'Lock Successful'),
      message: lockPeriod === 0
        ? tp('senateView.toast.stakedFlexible', 'Locked {amount} {ccy}, flexible', { amount, ccy: localCurrency.value })
        : tp('senateView.toast.stakedDays', 'Locked {amount} {ccy} for {days} days', { amount, ccy: localCurrency.value, days: lockPeriod }) })
  } catch (e: unknown) {
    notify({ type: 'error', title: t('senateView.toast.stakeFailed', 'Lock Failed'), message: errorMessage(e, t('senateView.toast.stakeFailedMsg', 'Failed to lock')) })
  } finally {
    isActing.value = false
  }
}

function handleUnstake(pos: StakingPosition) {
  selectedPosition.value = pos
  showUnstakeModal.value = true
}

async function confirmUnstake() {
  if (!selectedPosition.value) return
  isActing.value = true
  const amount = selectedPosition.value.amount
  try {
    await stakingStore.unstake(selectedPosition.value.id)
    await Promise.all([readMyStaking(), tegStore.fetchBalance()])
    showUnstakeModal.value = false
    selectedPosition.value = null
    notify({ type: 'success', title: t('senateView.toast.unstaked', 'Unlocked'), message: tp('senateView.toast.unstakedMsg', '{amount} {ccy} returned to liquid balance', { amount, ccy: localCurrency.value }) })
  } catch (e: unknown) {
    notify({ type: 'error', title: t('senateView.toast.unstakeFailed', 'Unlock Failed'), message: errorMessage(e, t('senateView.toast.unstakeFailedMsg', 'Failed to unlock')) })
  } finally {
    isActing.value = false
  }
}

async function handleClaimRewards() {
  isActing.value = true
  try {
    await stakingStore.claimRewards()
    await Promise.all([readMyStaking(), tegStore.fetchBalance()])
    notify({ type: 'success', title: t('senateView.toast.claimed', 'Payouts Claimed'), message: tp('senateView.toast.claimedMsg', '{ccy} payouts claimed to liquid balance', { ccy: localCurrency.value }) })
  } catch (e: unknown) {
    notify({ type: 'error', title: t('senateView.toast.claimFailed', 'Claim Failed'), message: errorMessage(e, t('senateView.toast.claimFailedMsg', 'Failed to claim')) })
  } finally {
    isActing.value = false
  }
}

async function handleVote(proposal: Proposal) {
  try {
    const result = await governanceStore.checkMyVote(proposal.id)
    if (result.hasVoted) return
  } catch { /* expected */ }
  selectedProposal.value = proposal
  showVoteModal.value = true
}

// §MEMBERSHIP — the vote in flight while a step-up is open: the proof goes with the SAME choice and reason.
const pendingMemberVote = ref<{ proposalId: string; choice: 'for' | 'against'; reason: string } | null>(null)
// a vote refused for the agent's missing gov.vote is kept, and sent again once its owner allowed the agent to vote
const actingAgentDid = computed(() => (authStore.activeAgent?.did as string | undefined) || null)
const voteRefusedForPermission = ref(false)
let voteAfterAllow: { proposalId: string; choice: 'for' | 'against'; reason: string } | null = null
async function onVoteAllowed() {
  voteRefusedForPermission.value = false
  notify({ type: 'success', title: t('membership.vote.allowed', 'This agent may vote now') })
  if (voteAfterAllow) {
    pendingMemberVote.value = voteAfterAllow
    voteAfterAllow = null
    await castAsMember()
  }
}
const stepUp = ref<StepUpChallenge | null>(null)
const stepUpError = ref('')

function cancelStepUp() {
  stepUp.value = null
  stepUpError.value = ''
  pendingMemberVote.value = null
}

async function castAsMember(extra: { totpCode?: string; challengeId?: string } = {}) {
  const v = pendingMemberVote.value
  if (!v || isActing.value) return
  isActing.value = true
  try {
    const out = await governanceStore.voteAsMember(v.proposalId, v.choice, v.reason, extra)
    onMemberOutcome(v.proposalId, out, !!(extra.totpCode || extra.challengeId))
  } catch (e: unknown) {
    const msg = errorMessage(e, t('senateView.toast.voteFailedMsg', 'Failed to vote'))
    if (stepUp.value) stepUpError.value = msg
    else notify({ type: 'error', title: t('senateView.toast.voteFailed', 'Vote Failed'), message: msg })
  } finally {
    isActing.value = false
  }
}

function onMemberOutcome(id: string, out: MemberVoteOutcome, sentProof: boolean) {
  if (out.kind === 'step_up') {
    // a second 428 after a proof means the proof was not accepted (a wrong code, a declined or expired challenge)
    stepUpError.value = sentProof ? (out.message || t('membership.stepUp.expired', 'This confirmation expired. Vote again to get a new one.')) : ''
    stepUp.value = out.stepUp
    showVoteModal.value = false
    return
  }
  showVoteModal.value = false
  selectedProposal.value = null
  const refusedVote = pendingMemberVote.value
  cancelStepUp()
  if (out.kind === 'needs_permission') {
    voteAfterAllow = refusedVote
    voteRefusedForPermission.value = true
    notify({ type: 'warning', title: t('membership.vote.needsPermission', 'This agent is not allowed to vote yet'),
      message: t('membership.vote.needsPermissionMsg', 'Allow it in the notice under your membership, and the vote is sent again.') })
    return
  }
  voteRefusedForPermission.value = false
  if (out.kind === 'cast') {
    // the server counts points (weight x points_per_weight); the toast names the weight, as the panel does
    const per = membershipStats.value?.points_per_weight || 100
    const w = out.votingPower != null ? weightLabel(out.votingPower / per, appLocale()) : memberWeightText.value
    notify({ type: 'success', title: t('membership.vote.cast', 'Vote cast'),
      message: tp('membership.vote.castMsg', 'Your vote on proposal #{id} counts with weight {w}.', { id, w }) })
  } else if (out.kind === 'not_member') {
    notify({ type: 'warning', title: t('membership.vote.notMember', 'Only members vote here') })
    void reloadMembership()
  } else if (out.kind === 'second_factor_required') {
    notify({ type: 'warning', title: t('membership.vote.secondFactor', 'Set up a confirmation first'),
      message: t('membership.vote.secondFactorMsg', 'This registry needs every binding vote confirmed. Enrol your phone in Pocket or turn on two-factor sign-in in Settings, then vote again.') })
  } else if (out.kind === 'already_voted') {
    notify({ type: 'info', title: t('membership.vote.alreadyVoted', 'You already voted'),
      message: t('membership.vote.alreadyVotedMsg', 'One vote per member: you voted on this proposal through another agent.') })
  }
}

async function submitVote(choice: 'for' | 'against', reason: string) {
  if (!selectedProposal.value) return
  if (memberMode.value) {
    pendingMemberVote.value = { proposalId: String(selectedProposal.value.id), choice, reason }
    await castAsMember()
    return
  }
  isActing.value = true
  const id = selectedProposal.value.id
  try {
    await governanceStore.vote(id, choice, reason)
    showVoteModal.value = false
    selectedProposal.value = null
    notify({ type: 'success', title: t('senateView.toast.voteCast', 'Vote Cast'),
      message: choice === 'for'
        ? tp('senateView.toast.votedFor', 'Voted for on proposal #{id}', { id })
        : tp('senateView.toast.votedAgainst', 'Voted against on proposal #{id}', { id }) })
  } catch (e: unknown) {
    notify({ type: 'error', title: t('senateView.toast.voteFailed', 'Vote Failed'), message: errorMessage(e, t('senateView.toast.voteFailedMsg', 'Failed to vote')) })
  } finally {
    isActing.value = false
  }
}

async function createProposal(payload: { title: string; description: string; type: string; duration_seconds?: number; policy_diff?: Record<string, unknown> }) {
  isActing.value = true
  try {
    await governanceStore.createProposal(payload)
    showProposalModal.value = false
    notify({ type: 'success', title: t('senateView.toast.proposalCreated', 'Proposal Created'), message: payload.title })
  } catch (e: unknown) {
    notify({ type: 'error', title: t('senateView.toast.proposalFailed', 'Proposal Failed'), message: errorMessage(e, t('senateView.toast.proposalFailedMsg', 'Failed to create')) })
  } finally {
    isActing.value = false
  }
}

/** §FRAMEPOLICY — the tally payload now names the policy that judged it and,
 *  for a policy_change, whether the document actually moved. */
interface TallyResult {
  status?: string
  pass_rate?: number
  policy_version?: number | null
  policy_source?: 'factory_default' | 'amended' | null
  quorum_percent?: number | null
  pass_percent?: number | null
  policy_applied?: boolean | null
  policy_new_version?: number | null
  policy_apply_error?: string | null
}

async function handleTally(proposal: Proposal) {
  isActing.value = true
  try {
    const result = await governanceStore.tallyProposal(proposal.id) as TallyResult
    await governanceStore.fetchProposals()

    // §FRAMEPOLICY — say WHICH policy judged this tally. The thresholds are the
    // frame's own declared rules now, not literals in the router, so a result
    // that does not name its policy cannot be reproduced later.
    const underPolicy = result.policy_version != null
      ? ' · ' + tp('senateView.toast.underPolicy', 'under policy v{v}', { v: result.policy_version })
        + (result.policy_source === 'factory_default' ? ' ' + t('senateView.toast.factoryDefault', '(factory default)') : '')
      : ''
    const thresholds = (result.quorum_percent != null && result.pass_percent != null)
      ? ' · ' + tp('senateView.toast.thresholds', 'quorum {q}% / pass {p}%', { q: result.quorum_percent, p: result.pass_percent })
      : ''
    notify({
      type: 'success', title: t('senateView.toast.tallied', 'Proposal Tallied'),
      message: tp('senateView.toast.talliedMsg', '#{id}: {status} — {rate}% approval', { id: proposal.id, status: result.status, rate: result.pass_rate })
        + thresholds + underPolicy,
    })

    // A policy_change that PASSED but whose policy did NOT move is the one
    // outcome that used to be invisible: the apply path logged and continued,
    // and the caller saw a plain PASSED.
    if (result.policy_applied === false) {
      notify({
        type: 'error', title: t('senateView.toast.policyNotApplied', 'Policy NOT applied'),
        message: tp('senateView.toast.policyNotAppliedMsg', '#{id} passed but the policy document did not change', { id: proposal.id })
          + (result.policy_apply_error ? `: ${result.policy_apply_error}` : '')
          + t('senateView.toast.rulesUnchanged', '. The rules are unchanged.'),
      })
    } else if (result.policy_applied === true) {
      notify({
        type: 'success', title: t('senateView.toast.policyApplied', 'Policy applied'),
        message: tp('senateView.toast.policyAppliedMsg', "#{id} moved this frame's policy to v{v}", { id: proposal.id, v: result.policy_new_version }),
      })
    }
  } catch (e: unknown) {
    notify({ type: 'error', title: t('senateView.toast.tallyFailed', 'Tally Failed'), message: errorMessage(e, t('senateView.toast.tallyFailedMsg', 'Failed to tally')) })
  } finally {
    isActing.value = false
  }
}

async function refreshGovernance() {
  await Promise.all([governanceStore.fetchProposals(), governanceStore.fetchVotingPower(), governanceStore.fetchStats()])
}
</script>

<style scoped>
/* ── Design tokens ──────────────────────────────────────────────────────── */
.sn-view {
  /* §2026-06-07 — primary accent now theme-reactive (was a fixed cyan that was
     "out of line" on the sovereign/red theme). Follows body.theme-{neural|sovereign}
     via --nc-primary. (Commander: align Senate's blue/cyan with theme usage.) */
  --sn-cyan:   var(--nc-primary, rgb(0, 210, 210));
  --sn-green:  rgb(34, 197, 94);
  --sn-red:    rgb(239, 68, 68);
  --sn-amber:  rgb(251, 191, 36);
  --sn-purple: rgb(167, 139, 250);
  /* §MCPTEST30 (V0558): the federation tab's and its dialogs' colour names, defined nowhere until now (an undefined var()
     paints nothing: the vote dialog had no background) */
  --cyan:  var(--sn-cyan);
  --green: var(--sn-green);
  --amber: var(--sn-amber);
  --muted: #7b91b2;
  --text-bright: var(--nc-text-primary, #e6edf6);
  --text: var(--nc-text-muted, #c9d4e3);
  --bg: var(--sn-surface);
  --border: var(--sn-border);
  --border-bright: var(--nc-border-strong, rgba(var(--nc-primary-rgb), 0.35));
  --sn-surface: var(--nc-surface, #111827);
  --sn-border:  var(--nc-border, rgba(var(--nc-primary-rgb),0.15));

  max-width: 1400px;
  margin: 0 auto;
  padding: 1.5rem;
  background: var(--nc-deep, #080e1a);
  min-height: 100%;
  position: relative;
}
/* 2026-05-07: content above ambient bg layer. */
.sn-content {
  position: relative;
  z-index: 1;
}

/* ── Header ─────────────────────────────────────────────────────────────── */
.sn-header {
  display: flex; align-items: flex-start; justify-content: space-between;
  margin-bottom: 2rem; gap: 1rem;
}
.sn-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 1.6rem; font-weight: 700;
  color: var(--sn-cyan); letter-spacing: -0.02em;
}
.sn-subtitle {
  font-size: 0.8rem; color: #7b91b2;
  margin-top: 0.3rem; letter-spacing: 0.04em;
}

/* Tabs */
.sn-tabs {
  display: flex; gap: 2px;
  background: rgba(0,0,0,0.3);
  border: 1px solid var(--sn-border);
  border-radius: 8px; padding: 3px;
}
.sn-tab {
  display: flex; align-items: center; gap: 0.4rem;
  padding: 0.4rem 1.1rem;
  border-radius: 6px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem; font-weight: 600;
  letter-spacing: 0.08em; text-transform: uppercase;
  color: #8191a5; background: transparent; border: none;
  cursor: pointer; transition: all 0.15s;
}
.sn-tab--active { background: rgba(var(--nc-primary-rgb),0.12); color: var(--sn-cyan); }
/* a phone: the strip scrolls sideways inside its own box, where four or five tabs ran past the screen and the last one
   (Commons) could not be reached (the camera, 2026-10-13, Pixel 7) */
@media (max-width: 640px) {
  .sn-header { flex-direction: column; align-items: stretch; }
  .sn-tabs { max-width: 100%; min-width: 0; overflow-x: auto; scrollbar-width: none; -webkit-overflow-scrolling: touch; }
  .sn-tabs::-webkit-scrollbar { display: none; }
  .sn-tab { flex: 0 0 auto; padding: 0.4rem 0.8rem; }
}
.sn-tab__icon { width: 14px; height: 14px; }

/* Loader */
.sn-loader {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 1rem; padding: 5rem; color: #7b91b2; font-size: 0.85rem;
}
.sn-loader__ring {
  width: 40px; height: 40px;
  border: 3px solid rgba(var(--nc-primary-rgb),0.15);
  border-top-color: var(--sn-cyan);
  border-radius: 50%; animation: sn-spin 0.8s linear infinite;
}

/* ── Stat cards ─────────────────────────────────────────────────────────── */
.sn-stats {
  display: grid; grid-template-columns: repeat(4, 1fr);
  gap: 1rem; margin-bottom: 1.5rem;
}
@media (max-width:900px)  { .sn-stats { grid-template-columns: repeat(2,1fr); } }
@media (max-width:500px)  { .sn-stats { grid-template-columns: 1fr 1fr; } }

.sn-stat-card {
  background: var(--sn-surface);
  border: 1px solid var(--sn-border);
  border-radius: 10px; overflow: hidden; position: relative;
}
.sn-stat-card__accent {
  position: absolute; left:0; top:0; bottom:0; width: 3px;
}
.sn-stat-card__body { padding: 1rem 1rem 1rem 1.25rem; }
.sn-stat-card__label {
  font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.07em;
  color: #7b91b2; margin-bottom: 0.4rem;
}
.sn-stat-card__value {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 1.4rem; font-weight: 700; color: #e2e8f0; line-height: 1;
}

/* ── Action bar ─────────────────────────────────────────────────────────── */
.sn-action-bar {
  display: flex; gap: 0.75rem; margin-bottom: 1.5rem; flex-wrap: wrap;
}
.sn-cta-btn {
  display: inline-flex; align-items: center; gap: 0.4rem;
  padding: 0.5rem 1.1rem;
  background: var(--sn-cyan); color: #060b14;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem; font-weight: 700;
  letter-spacing: 0.08em; text-transform: uppercase;
  border: none; border-radius: 7px; cursor: pointer;
  transition: background 0.15s;
}
.sn-cta-btn:hover { background: rgba(var(--nc-primary-rgb),0.82); }

.sn-ghost-btn {
  display: inline-flex; align-items: center; gap: 0.4rem;
  padding: 0.5rem 1.1rem;
  background: transparent; color: #8fa3be;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem; font-weight: 600;
  letter-spacing: 0.08em; text-transform: uppercase;
  border: 1px solid var(--sn-border); border-radius: 7px; cursor: pointer;
  transition: all 0.15s;
}
.sn-ghost-btn:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb),0.07); color: var(--sn-cyan); }
.sn-ghost-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* ── Section ─────────────────────────────────────────────────────────────── */
.sn-tab-content { display: flex; flex-direction: column; gap: 1.5rem; }
.sn-section {}
.sn-section-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.1em;
  color: #7b91b2; margin-bottom: 1rem;
}

/* Empty state */
.sn-empty {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 0.75rem; padding: 3.5rem;
  background: var(--sn-surface); border: 1px solid var(--sn-border);
  border-radius: 10px; color: #7b91b2; text-align: center;
}
.sn-empty__title { font-size: 1rem; font-weight: 600; color: #8191a5; }
.sn-empty__sub   { font-size: 0.82rem; }
.sn-staking-off {
  margin: 0 0 14px; padding: 10px 14px; border-radius: 10px;
  border: 1px solid rgba(var(--nc-primary-rgb, 34,211,238), 0.35); background: rgba(var(--nc-primary-rgb, 34,211,238), 0.06);
  font-size: 13px; line-height: 1.5;
}
.sn-staking-off p { margin: 0; }
.sn-staking-off p + p { margin-top: 4px; }

/* ── Positions grid ──────────────────────────────────────────────────────── */
.sn-positions-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.85rem;
}
@media (max-width:1000px) { .sn-positions-grid { grid-template-columns: repeat(2,1fr); } }
@media (max-width:580px)  { .sn-positions-grid { grid-template-columns: 1fr; } }

.sn-pos-card {
  background: var(--sn-surface);
  border: 1px solid var(--sn-border);
  border-left: 3px solid transparent;
  border-radius: 10px; padding: 1rem 1rem 1rem 1.1rem;
}
.sn-pos-card--ready  { border-left-color: var(--sn-green); }
.sn-pos-card--locked { border-left-color: var(--sn-amber); }

.sn-pos-card__head {
  display: flex; justify-content: space-between; align-items: flex-start;
  margin-bottom: 0.2rem;
}
.sn-pos-card__amount {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 1.05rem; font-weight: 700; color: #e2e8f0;
}
.sn-pos-apy-badge {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem; font-weight: 700;
  background: rgba(34,197,94,0.12); color: var(--sn-green);
  padding: 0.15rem 0.5rem; border-radius: 9999px;
}
.sn-pos-card__type { font-size: 0.75rem; color: #7b91b2; margin-bottom: 0.75rem; }

.sn-pos-rows { display: flex; flex-direction: column; gap: 0.35rem; margin-bottom: 0.85rem; }
.sn-pos-row {
  display: flex; justify-content: space-between;
  font-size: 0.78rem; color: #8191a5;
}
.sn-pos-row span:last-child { color: #c8d6e8; }

.sn-unstake-btn {
  width: 100%; padding: 0.5rem;
  background: rgba(var(--nc-primary-rgb),0.1); color: var(--sn-cyan);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem; font-weight: 700; letter-spacing: 0.08em;
  border: 1px solid rgba(var(--nc-primary-rgb),0.25); border-radius: 7px;
  cursor: pointer; transition: all 0.15s; text-align: center;
}
.sn-unstake-btn:hover { background: rgba(var(--nc-primary-rgb),0.18); }

.sn-locked-bar {
  width: 100%; padding: 0.5rem;
  background: rgba(251,191,36,0.06); color: #7b91b2;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem; letter-spacing: 0.06em;
  border: 1px solid rgba(251,191,36,0.15); border-radius: 7px;
  text-align: center;
}

/* ── Lock Tier cards ──────────────────────────────────────────────────────── */
.sn-tier-grid {
  display: grid; gap: 1rem;
}
@media (max-width:900px) { .sn-tier-grid { grid-template-columns: repeat(3,1fr) !important; } }
@media (max-width:580px) { .sn-tier-grid { grid-template-columns: repeat(2,1fr) !important; } }

.sn-tier-card {
  background: var(--sn-surface);
  border: 1px solid rgba(var(--nc-primary-rgb),0.15);
  border-radius: 12px; padding: 1.5rem 1rem;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
  display: flex; flex-direction: column; align-items: center; gap: 0.4rem;
}
.sn-tier-card:hover {
  border-color: rgba(var(--nc-primary-rgb),0.45);
  background: rgba(var(--nc-primary-rgb),0.04);
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(var(--nc-primary-rgb),0.08);
}

.sn-tier-card__icon {
  width: 40px; height: 40px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  margin-bottom: 0.25rem;
}
.sn-tier-card__icon svg { width: 22px; height: 22px; }

.sn-tier-card--flex .sn-tier-card__icon {
  background: rgba(34,197,94,0.1); color: var(--sn-green);
}
.sn-tier-card--lock .sn-tier-card__icon {
  background: rgba(251,191,36,0.1); color: var(--sn-amber);
}

.sn-tier-card__period {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.75rem; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.1em;
  color: #8fa3be;
}
.sn-tier-card__apy {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 2rem; font-weight: 800;
  color: var(--sn-cyan); line-height: 1;
}
.sn-tier-card__apy-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem; letter-spacing: 0.12em; text-transform: uppercase;
  color: #7b91b2;
}

.sn-tier-card__badge {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem; font-weight: 700;
  padding: 0.2rem 0.65rem; border-radius: 9999px;
  margin-top: 0.1rem;
}
.sn-tier-card__badge--flex  { background: rgba(34,197,94,0.12);  color: var(--sn-green);  border: 1px solid rgba(34,197,94,0.25);  }
.sn-tier-card__badge--bonus { background: rgba(251,191,36,0.12); color: var(--sn-amber);  border: 1px solid rgba(251,191,36,0.25); }

.sn-tier-card__desc {
  font-size: 0.72rem; color: #7b91b2; margin-top: 0.1rem;
}
.sn-tier-card__cta {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem; font-weight: 700;
  color: var(--sn-cyan); opacity: 0;
  transition: opacity 0.15s; margin-top: 0.25rem;
}
.sn-tier-card:hover .sn-tier-card__cta { opacity: 1; }
/* a device with no hover (a phone): the card's call to action is shown without one */
@media (hover: none) { .sn-tier-card__cta { opacity: 1; } }

/* ── veToken power box ───────────────────────────────────────────────────── */
.sn-vepower-box {
  background: var(--sn-surface);
  border: 1px solid var(--sn-border);
  border-radius: 10px; padding: 1rem 1.25rem;
  margin-bottom: 0.5rem;
}
.sn-vepower-box__title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.1em;
  color: #7b91b2; margin-bottom: 0.75rem;
}
.sn-vepower-list { display: flex; flex-direction: column; gap: 0.4rem; }
.sn-vepower-row {
  display: flex; align-items: center; justify-content: space-between;
  font-size: 0.8rem; padding: 0.25rem 0;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.05);
}
.sn-vepower-row:last-child { border-bottom: none; }
.sn-vepower-row__left { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
.sn-vepower-row__amount { font-family: 'IBM Plex Mono', monospace; color: #c8d6e8; font-size: 0.78rem; }
.sn-vepower-row__sep    { color: #7b91b2; }
.sn-vepower-row__type   { color: #8191a5; font-size: 0.75rem; }
.sn-vepower-row__rem    { color: #7b91b2; font-size: 0.73rem; }
.sn-vepower-row__ve {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.78rem; font-weight: 700; color: #7b91b2;
}
.sn-vepower-row__ve--active { color: rgba(var(--nc-primary-rgb),0.8); }

/* ── Governance command bar ──────────────────────────────────────────────── */
.sn-gov-bar {
  display: flex; align-items: center; justify-content: space-between;
  gap: 1rem; margin-bottom: 1.25rem; flex-wrap: wrap;
}
.sn-pills { display: flex; gap: 0.4rem; flex-wrap: wrap; }
.sn-pill {
  display: flex; align-items: center; gap: 0.3rem;
  padding: 0.35rem 0.85rem;
  border-radius: 9999px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem; font-weight: 600;
  letter-spacing: 0.07em; text-transform: uppercase;
  background: rgba(255,255,255,0.03);
  border: 1px solid var(--sn-border);
  color: #8191a5; cursor: pointer; transition: all 0.15s;
}
.sn-pill:hover  { background: rgba(var(--nc-primary-rgb),0.07); color: var(--sn-cyan); }
.sn-pill--active { background: rgba(var(--nc-primary-rgb),0.12); color: var(--sn-cyan); border-color: rgba(var(--nc-primary-rgb),0.35); }
.sn-pill__badge {
  background: rgba(var(--nc-primary-rgb),0.15); color: var(--sn-cyan);
  border-radius: 9999px; padding: 0 0.4rem; font-size: 0.62rem;
  min-width: 18px; text-align: center;
}

.sn-icon-btn {
  width: 34px; height: 34px; border-radius: 7px;
  background: var(--sn-surface); border: 1px solid var(--sn-border);
  color: #8191a5; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: all 0.15s;
}
.sn-icon-btn:hover { background: rgba(var(--nc-primary-rgb),0.07); color: var(--sn-cyan); }

/* ── Proposal cards ──────────────────────────────────────────────────────── */
.sn-proposals-list { display: flex; flex-direction: column; gap: 0.85rem; }

.sn-proposal-card {
  background: var(--sn-surface);
  border: 1px solid var(--sn-border);
  border-left: 3px solid transparent;
  border-radius: 10px; padding: 1.25rem 1.25rem 1.25rem 1.35rem;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.sn-proposal-card:hover {
  box-shadow: 0 0 18px rgba(var(--nc-primary-rgb),0.06);
  border-color: rgba(var(--nc-primary-rgb),0.25);
}
.sn-proposal-card--active { border-left-color: var(--sn-green); }
.sn-proposal-card--passed { border-left-color: rgba(var(--nc-primary-rgb),0.7); }
.sn-proposal-card--failed { border-left-color: var(--sn-red); }
.sn-proposal-card--ended  { border-left-color: var(--sn-amber); }

.sn-proposal-card__head {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 0.6rem; gap: 0.75rem;
}
.sn-proposal-card__head-left { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
.sn-proposal-card__head-right {
  display: flex; align-items: center; gap: 0.3rem;
  font-size: 0.73rem; color: #7b91b2; flex-shrink: 0;
}

.sn-prop-id {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem; color: #7b91b2;
}
.sn-prop-reason { font-size: 0.72rem; opacity: 0.85; letter-spacing: 0.02em; }
.sn-prop-status-pill, .sn-prop-type-pill {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem; font-weight: 600;
  letter-spacing: 0.07em; text-transform: uppercase;
  padding: 0.15rem 0.5rem; border-radius: 9999px;
}
.sn-prop-status-pill--active   { background: rgba(34,197,94,0.12);   color: var(--sn-green); }
.sn-prop-status-pill--passed   { background: rgba(var(--nc-primary-rgb),0.1);    color: var(--sn-cyan); }
.sn-prop-status-pill--failed   { background: rgba(239,68,68,0.12);   color: #f26464; }
.sn-prop-status-pill--ended    { background: rgba(251,191,36,0.12);  color: var(--sn-amber); }
.sn-prop-status-pill--pending  { background: rgba(107,114,128,0.12); color: #9ca3af; }

.sn-prop-type-pill--standard { background: rgba(var(--nc-primary-rgb),0.07); color: rgba(var(--nc-primary-rgb),0.7); }
.sn-prop-type-pill--policy   { background: rgba(167,139,250,0.1); color: var(--sn-purple); }

.sn-proposal-card__title {
  font-size: 0.95rem; font-weight: 600; color: #e2e8f0;
  margin-bottom: 0.15rem; line-height: 1.4;
}
.sn-proposal-card__proposer {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem; color: #7b91b2; margin-bottom: 0.75rem;
}
.sn-proposal-card__desc {
  font-size: 0.83rem; color: #8fa3be; line-height: 1.55;
  margin-bottom: 1rem;
}

/* Vote bar */
.sn-vote-bar-section { margin-bottom: 1rem; }
.sn-vote-counts {
  display: flex; gap: 1.5rem; margin-bottom: 0.4rem;
}
.sn-vote-count {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.75rem; font-weight: 600;
}
.sn-vote-count--for     { color: var(--sn-green); }
.sn-vote-count--against { color: var(--sn-red); }

.sn-vote-bar-track {
  position: relative; height: 6px;
  background: rgba(255,255,255,0.06);
  border-radius: 9999px; overflow: visible;
  margin-bottom: 0.35rem;
}
.sn-vote-bar-fill {
  position: absolute; top: 0; height: 100%; border-radius: 9999px;
  transition: width 0.4s ease;
}
.sn-vote-bar-fill--for     { background: var(--sn-green); left: 0; }
.sn-vote-bar-fill--against { background: var(--sn-red); }

.sn-quorum-marker {
  position: absolute; top: -4px; bottom: -4px; width: 2px;
  background: var(--sn-amber); border-radius: 1px;
  opacity: 0.7;
}
.sn-quorum-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem; color: #7b91b2;
}

/* Proposal footer */
.sn-proposal-card__foot {
  display: flex; align-items: center; justify-content: space-between;
  padding-top: 0.75rem;
  border-top: 1px solid rgba(var(--nc-primary-rgb),0.07);
}

.sn-voted-badge {
  display: flex; align-items: center; gap: 0.3rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
  padding: 0.25rem 0.65rem; border-radius: 9999px;
}
.sn-voted-badge--for    { background: rgba(34,197,94,0.12); color: var(--sn-green); border: 1px solid rgba(34,197,94,0.25); }
.sn-voted-badge--against { background: rgba(239,68,68,0.12); color: #f26464;   border: 1px solid rgba(239,68,68,0.25); }

.sn-vote-btn {
  padding: 0.4rem 1rem;
  background: rgba(var(--nc-primary-rgb),0.1); color: var(--sn-cyan);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem; font-weight: 700; letter-spacing: 0.07em; text-transform: uppercase;
  border: 1px solid rgba(var(--nc-primary-rgb),0.25); border-radius: 6px;
  cursor: pointer; transition: all 0.15s;
}
.sn-vote-btn:hover { background: rgba(var(--nc-primary-rgb),0.18); }

.sn-tally-btn {
  padding: 0.4rem 1rem;
  background: rgba(251,191,36,0.1); color: var(--sn-amber);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem; font-weight: 700; letter-spacing: 0.07em; text-transform: uppercase;
  border: 1px solid rgba(251,191,36,0.25); border-radius: 6px;
  cursor: pointer; transition: all 0.15s;
}
.sn-tally-btn:hover { background: rgba(251,191,36,0.2); }

/* Animation */
@keyframes sn-spin { to { transform: rotate(360deg); } }

/* ── Funding Tab Styles ──────────────────────────────────────────────────── */
.fund-table-wrap { overflow-x: auto; border: 1px solid var(--sn-border); border-radius: 8px; background: var(--sn-surface); }
.fund-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
.fund-table th { font-family: 'IBM Plex Mono', monospace; font-size: 0.6rem; letter-spacing: 0.12em; color: rgba(148,163,184,0.4); padding: 10px 14px; text-align: left; border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.08); background: rgba(0,0,0,0.2); }
.fund-table td { padding: 12px 14px; border-bottom: 1px solid rgba(255,255,255,0.03); vertical-align: middle; }
.fund-table tbody tr { transition: background 0.1s; }
.fund-table tbody tr:hover { background: rgba(var(--nc-primary-rgb),0.02); }
.fund-td-did { font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem; color: rgba(148,163,184,0.5); max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fund-td-amount { font-family: 'IBM Plex Mono', monospace; font-weight: 600; color: var(--sn-cyan); white-space: nowrap; }
.fund-td-reason { color: rgba(148,163,184,0.6); font-size: 0.78rem; max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fund-td-date { font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem; color: rgba(148,163,184,0.4); white-space: nowrap; }
.fund-td-actions { display: flex; align-items: center; gap: 6px; flex-wrap: nowrap; }
.fund-btn { padding: 5px 12px; border-radius: 5px; cursor: pointer; font-family: 'IBM Plex Mono', monospace; font-size: 0.68rem; font-weight: 600; letter-spacing: 0.05em; border: 1px solid transparent; transition: all 0.15s; white-space: nowrap; }
.fund-btn--approve { background: rgba(34,197,94,0.1); border-color: rgba(34,197,94,0.3); color: rgba(34,197,94,0.9); }
.fund-btn--approve:hover { background: rgba(34,197,94,0.2); border-color: rgba(34,197,94,0.5); }
.fund-btn--reject { background: rgba(239,68,68,0.08); border-color: rgba(239,68,68,0.25); color: rgba(239,68,68,0.8); }
.fund-btn--reject:hover { background: rgba(239,68,68,0.15); border-color: rgba(239,68,68,0.4); }
.fund-btn--confirm { background: rgba(34,197,94,0.15); border-color: rgba(34,197,94,0.4); color: rgba(34,197,94,0.9); }
.fund-btn--confirm:hover { background: rgba(34,197,94,0.25); }
.fund-btn--confirm:disabled { opacity: 0.4; cursor: not-allowed; }
.fund-btn--reject-confirm { background: rgba(239,68,68,0.12); border-color: rgba(239,68,68,0.3); color: rgba(239,68,68,0.9); }
.fund-btn--reject-confirm:hover { background: rgba(239,68,68,0.2); }
.fund-btn--reject-confirm:disabled { opacity: 0.4; cursor: not-allowed; }
.fund-btn--cancel { background: rgba(255,255,255,0.04); border-color: rgba(255,255,255,0.1); color: rgba(148,163,184,0.6); }
.fund-btn--cancel:hover { background: rgba(255,255,255,0.08); color: rgba(226,232,240,0.8); }
.fund-inline-input { width: 80px; padding: 4px 8px; background: rgba(255,255,255,0.04); border: 1px solid rgba(var(--nc-primary-rgb),0.2); border-radius: 4px; color: #e2e8f0; font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; outline: none; }
.fund-inline-input:focus { border-color: rgba(var(--nc-primary-rgb),0.5); }
.fund-inline-input--wide { width: 140px; }
.fund-status-badge { display: inline-block; font-family: 'IBM Plex Mono', monospace; font-size: 0.58rem; letter-spacing: 0.1em; padding: 2px 8px; border-radius: 4px; border: 1px solid; font-weight: 600; }

/* Load more */
.sn-load-more { text-align: center; margin-top: 1rem; }

/* Federation tab */
.sn-fed-origin { font-size: 0.78rem; color: var(--muted); margin: 4px 0 8px; }
.sn-fed-origin strong { color: var(--text-bright); }
.sn-fed-peers { margin-bottom: 18px; display: grid; gap: 12px; }
.sn-fed-peers__title { font-size: 0.85rem; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); margin: 0; }
.sn-fed-peers__none { font-size: 0.8rem; color: var(--muted); margin: 4px 0 16px; }
.sn-fed-peers__error { font-size: 0.78rem; color: var(--amber); margin: 0 0 8px; }
.sn-fed-registries { display: inline-flex; align-items: center; gap: 4px; padding: 2px 10px; background: rgba(var(--nc-primary-rgb),0.08); border: 1px solid rgba(var(--nc-primary-rgb),0.2); border-radius: 12px; color: var(--cyan); font-weight: 600; font-size: 0.72rem; letter-spacing: 0.03em; }
.sn-fed-veto-timer { color: #f59e0b; font-weight: 500; }
.sn-fed-policy-diff { background: rgba(0,0,0,0.3); border: 1px solid rgba(var(--nc-primary-rgb),0.1); border-radius: 6px; padding: 10px; margin-top: 10px; overflow-x: auto; }
.sn-fed-policy-diff pre { font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem; color: var(--green); margin: 0; white-space: pre-wrap; }
.sn-modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.sn-modal { background: var(--bg); border: 1px solid var(--border-bright); border-radius: 12px; padding: 24px; max-width: 480px; width: 90%; }
.sn-modal__title { font-family: 'IBM Plex Mono', monospace; font-size: 1rem; font-weight: 700; color: var(--text-bright); margin: 0 0 8px; }
.sn-modal__sub { font-size: 0.85rem; color: var(--text); margin: 0 0 12px; }

/* ════════ AAA+ polish — 2026-06-07 (additive; no template/logic change) ════════ */
/* P1 layout/hierarchy — stat cards lift on hover; section titles get an accent bar */
.sn-stat-card { transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease; }
.sn-stat-card:hover { transform: translateY(-2px); border-color: rgba(var(--nc-primary-rgb),0.3); box-shadow: 0 14px 34px -22px rgba(var(--nc-primary-rgb),0.55); }
.sn-section-title { position: relative; padding-left: 11px; }
.sn-section-title::before { content:''; position:absolute; left:0; top:3px; bottom:3px; width:3px; border-radius:2px; background: var(--sn-cyan); opacity:.6; }
/* P2 motion/states — active-tab underline glow + gentle card entry */
.sn-tab--active { box-shadow: inset 0 -2px 0 var(--sn-cyan); }
.sn-stat-card, .sn-pos-card, .sn-tier-card { animation: sn-rise .28s ease both; }
@keyframes sn-rise { from { opacity:0; transform: translateY(6px); } to { opacity:1; transform:none; } }
/* P3 data feedback — position cards lift; rows respond */
.sn-pos-card { transition: border-color .18s ease, box-shadow .18s ease; }
.sn-pos-card:hover { box-shadow: 0 12px 30px -22px rgba(var(--nc-primary-rgb),0.5); }
.sn-pos-row { transition: color .14s ease; }
/* P4 a11y — visible focus ring on every interactive element */
.sn-view :is(button, input, select, [tabindex]):focus-visible { outline: 2px solid rgba(var(--nc-primary-rgb),0.6); outline-offset: 2px; border-radius: 6px; }
/* P5 micro-interactions & cohesion — tabular numerals, button press */
.sn-stat-card__value, .sn-pos-card__amount, .sn-tier-card__apy, .sn-tier-card__period { font-variant-numeric: tabular-nums; }
.sn-cta-btn, .sn-unstake-btn { transition: transform .12s ease, background .15s ease; }
.sn-cta-btn:not(:disabled):active, .sn-unstake-btn:not(:disabled):active { transform: translateY(1px); }
@media (prefers-reduced-motion: reduce) {
  .sn-stat-card, .sn-pos-card, .sn-tier-card { animation: none !important; }
  .sn-stat-card:hover { transform: none; }
}

/* §2026-06-07 premium-glass restyle — flat boxes → layered glass (Commander) */
.sn-stat-card, .sn-tier-card, .sn-vepower-box, .sn-pos-card {
  /* §2026-06-07 — alpha 0.6→0.48 + blur 16→18 to EXACTLY match the approved
     Forex/Staking sk-card glass. (Commander: apply those boxes to Senate too.) */
  background:
    linear-gradient(165deg, rgba(255,255,255,0.07), rgba(255,255,255,0.014) 46%, rgba(255,255,255,0) 74%),
    rgba(15, 21, 34, 0.48);
  border-radius: 14px;
  backdrop-filter: blur(18px) saturate(1.1);
  -webkit-backdrop-filter: blur(18px) saturate(1.1);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.05), 0 16px 38px -28px rgba(0,0,0,0.9);
}
.sn-stat-card:hover, .sn-tier-card:hover {
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.08), 0 22px 50px -26px rgba(0,0,0,0.95);
}
/* stat-card left accent rail (premium financial marker) */
.sn-stat-card { position: relative; overflow: hidden; }
.sn-stat-card::after {
  content:''; position:absolute; left:0; top:14px; bottom:14px; width:2px; border-radius:2px;
  background: linear-gradient(180deg, var(--sn-cyan), rgba(var(--nc-primary-rgb),0));
}
/* tabbed content container + section cards also glass, not flat slabs */
.sn-tab-content > .sn-section, .sn-vepower-box {
  border: 1px solid rgba(var(--nc-primary-rgb), 0.12);
}
/* monochrome marks replacing emoji (premium, not cartoonish) */
.sn-btn-ic { width: 13px; height: 13px; margin-right: 5px; vertical-align: -2px; }
.sn-vote-mark { font-weight: 700; opacity: 0.9; }
/* premium hero numbers — per-value colour glow + tabular */
.sn-stat-card__value { font-variant-numeric: tabular-nums; letter-spacing: -0.015em; text-shadow: 0 0 22px color-mix(in srgb, currentColor 20%, transparent); }
.sn-pos-card__amount, .sn-tier-card__apy { font-variant-numeric: tabular-nums; }
</style>
