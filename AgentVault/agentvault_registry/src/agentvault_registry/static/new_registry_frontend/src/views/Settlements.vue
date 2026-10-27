<template>
  <div class="settlements-view">

    <!-- Ambient background layer (matches AdminCanaries) -->
    <div class="stl-ambient" aria-hidden="true">
      <div class="stl-grid"></div>
      <div class="stl-scan"></div>
      <div class="stl-glow stl-glow-1"></div>
      <div class="stl-glow stl-glow-2"></div>
    </div>

    <!-- Hero strip — mirrors canary hero pattern -->
    <section class="stl-hero">
      <div class="stl-hero-inner">
        <div class="stl-chip-hero"><span class="stl-chip-dot"></span>{{ t('settlementsView.heroChip') }}</div>
        <h1 class="stl-h1">
          {{ t('settlementsView.h1a') }} <span class="stl-accent">{{ t('settlementsView.h1Accent') }}</span>
        </h1>
        <p class="stl-lead">{{ t('settlementsView.lead') }}</p>
      </div>
    </section>

    <div class="stl-content">

    <!-- Peer Auto-Slash Config (collapsible — 2026-05-08 polish).
         Section was taking the whole page when many peers configured;
         now collapses to a single header row by default. -->
    <div class="bg-gray-800/50 rounded-lg p-6 mb-8 border border-gray-700" v-if="peerConfigs.length > 0">
      <button
        type="button"
        class="w-full flex items-center justify-between text-left"
        @click="peerConfigsExpanded = !peerConfigsExpanded"
        :aria-expanded="peerConfigsExpanded"
        aria-controls="peer-auto-slash-list"
      >
        <div>
          <h2 class="text-lg font-semibold text-white">{{ t('settlementsView.perPeerThresholds') }}</h2>
          <p class="text-sm text-gray-400 mt-1" v-if="!peerConfigsExpanded">
            {{ t('settlementsView.peersConfigured', { n: peerConfigs.length }) }}
          </p>
        </div>
        <span class="text-cyan-400 text-xl select-none" aria-hidden="true">
          {{ peerConfigsExpanded ? '▾' : '▸' }}
        </span>
      </button>

      <div v-if="peerConfigsExpanded" id="peer-auto-slash-list" class="mt-4">
        <p v-if="peerWriteFailed && error" role="alert" class="text-sm text-red-400 mb-3" data-testid="stl-peer-write-failed">{{ error }}</p>
        <p class="text-sm text-gray-400 mb-4">
          {{ t('settlementsView.perPeerExplain') }}
        </p>
        <div class="space-y-3">
          <div
            v-for="peer in peerConfigs"
            :key="peer.id"
            class="flex items-center justify-between bg-gray-900/50 rounded-lg p-4 border border-gray-700"
          >
            <div>
              <span class="text-white font-medium">{{ peer.name }}</span>
              <span class="text-xs text-gray-500 ml-2">{{ peer.base_url }}</span>
            </div>
            <div class="flex items-center gap-4">
              <label class="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  :checked="peer.auto_slash_enabled"
                  @change="togglePeerAutoSlash(peer, $event)"
                  class="w-4 h-4 rounded-sm accent-cyan-500"
                />
                <span class="text-sm text-gray-300">{{ t('settlementsView.autoSlash') }}</span>
              </label>
              <div class="flex items-center gap-2">
                <span class="text-xs text-gray-500">{{ t('settlementsView.upTo') }}</span>
                <input
                  type="number"
                  :value="peer.auto_slash_max_avt"
                  @change="updatePeerThreshold(peer, $event)"
                  min="0"
                  class="w-24 bg-gray-800 border border-gray-600 rounded-sm px-2 py-1 text-white text-sm text-right"
                  :disabled="!peer.auto_slash_enabled"
                />
                <span class="text-xs text-gray-500">{{ localCurrency }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Stats Cards -->
    <div class="grid grid-cols-2 md:grid-cols-5 gap-4 mb-8" v-if="stats">
      <div class="bg-gray-800 rounded-lg p-4 border border-gray-700">
        <div class="text-2xl font-bold text-white">{{ stats.total }}</div>
        <div class="text-sm text-gray-400">{{ t('settlementsView.stats.total') }}</div>
      </div>
      <div class="bg-gray-800 rounded-lg p-4 border border-yellow-600/30">
        <div class="text-2xl font-bold text-yellow-400">{{ stats.pending }}</div>
        <div class="text-sm text-gray-400">{{ t('settlementsView.stats.pending') }}</div>
      </div>
      <div class="bg-gray-800 rounded-lg p-4 border border-green-600/30">
        <div class="text-2xl font-bold text-green-400">{{ stats.settled }}</div>
        <div class="text-sm text-gray-400">{{ t('settlementsView.stats.settled') }}</div>
      </div>
      <div class="bg-gray-800 rounded-lg p-4 border border-red-600/30">
        <div class="text-2xl font-bold text-red-400">{{ stats.failed + stats.expired }}</div>
        <div class="text-sm text-gray-400">{{ t('settlementsView.stats.failedExpired') }}</div>
      </div>
      <div class="bg-gray-800 rounded-lg p-4 border border-cyan-600/30">
        <div class="text-2xl font-bold text-cyan-400">{{ stats.total_minted_avt }}</div>
        <div class="text-sm text-gray-400">{{ t('settlementsView.stats.avtMinted') }}</div>
      </div>
    </div>

    <!-- Flow summary -->
    <div class="bg-gray-800/50 rounded-lg p-6 mb-8 border border-gray-700" v-if="stats">
      <h2 class="text-lg font-semibold text-white mb-4">{{ t('settlementsView.stats.avtFlowSummary') }}</h2>
      <div class="flex items-center gap-8">
        <div class="text-center">
          <div class="text-xl font-bold text-orange-400">{{ stats.total_requested_avt }}</div>
          <div class="text-xs text-gray-500">{{ t('settlementsView.stats.requested') }}</div>
        </div>
        <div class="text-gray-600">→</div>
        <div class="text-center">
          <div class="text-xl font-bold text-red-400">{{ stats.total_slashed_avt }}</div>
          <div class="text-xs text-gray-500">{{ t('settlementsView.stats.slashed') }}</div>
        </div>
        <div class="text-gray-600">→</div>
        <div class="text-center">
          <div class="text-xl font-bold text-green-400">{{ stats.total_minted_avt }}</div>
          <div class="text-xs text-gray-500">{{ t('settlementsView.stats.minted') }}</div>
        </div>
        <div class="ml-auto text-sm text-gray-500" v-if="stats.total_requested_avt > stats.total_slashed_avt">
          <span class="text-yellow-400"><svg class="stl-warn-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.6 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.6a2 2 0 0 0-3.4 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg></span> {{ stats.total_requested_avt - stats.total_slashed_avt }} {{ t('settlementsView.shortfallNote') }}
        </div>
      </div>
    </div>

    <!-- SF2: Stuck saga warning banner -->
    <div
      v-if="stuckSagas.length > 0"
      class="mb-6 bg-amber-900/30 border border-amber-700 rounded-lg p-4 flex items-center gap-3"
    >
      <span class="text-2xl"><svg class="stl-warn-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.6 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.6a2 2 0 0 0-3.4 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg></span>
      <div class="flex-1">
        <div class="text-amber-300 font-semibold">
          {{ stuckSagas.length }} {{ stuckSagas.length === 1 ? t('settlementsView.stuckSaga.banner1') : t('settlementsView.stuckSaga.bannerN') }}
        </div>
        <div class="text-amber-400 text-sm">
          {{ t('settlementsView.stuckSaga.body') }}
        </div>
      </div>
    </div>

    <!-- SF11: Peer config error banner -->
    <div v-if="peerConfigError" class="mb-6 bg-red-900/30 border border-red-700 rounded-lg p-3 text-sm text-red-300">
      {{ t('settlementsView.peerConfig') }}: {{ peerConfigError }}
    </div>

    <!-- Filter Bar (wraps on a phone, where Refresh ran past the screen; the camera, 2026-10-13) -->
    <div class="flex flex-wrap items-center gap-3 mb-6">
      <button
        v-for="f in filters"
        :key="f.value"
        @click="setActiveFilter(f.value)"
        :class="[
          'px-4 py-2 rounded-lg text-sm font-medium transition-all',
          activeFilter === f.value
            ? 'bg-cyan-700 text-white'
            : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-200'
        ]"
      >
        {{ f.label }}
      </button>
      <button
        @click="refresh"
        class="ml-auto px-4 py-2 rounded-lg text-sm bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-white transition-all"
      >
        ↻ {{ t('common.refresh') }}
      </button>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="text-center py-12">
      <div class="animate-spin h-8 w-8 border-2 border-cyan-400 border-t-transparent rounded-full mx-auto mb-4"></div>
      <p class="text-gray-400">{{ t('settlementsView.loading') }}</p>
    </div>

    <!-- §FESUITE (2026-10-05): a failed list read is said in the list's place, never as "no settlements" -->
    <div v-else-if="listFailed && settlements.length === 0" class="py-12" data-testid="stl-list-failed">
      <ReadFailedNotice :retry="refresh" />
    </div>

    <!-- Empty State -->
    <div v-else-if="filteredSettlements.length === 0" class="text-center py-16">
      <div class="mb-4 flex justify-center" style="color: rgba(var(--stl-cyan-rgb), 0.45);">
        <svg width="58" height="58" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v18"/><path d="M7 21h10"/><path d="M5 7h14l-2-3H7z"/><path d="m5 7-3 6a4 4 0 0 0 6 0z"/><path d="m19 7-3 6a4 4 0 0 0 6 0z"/></svg>
      </div>
      <h3 class="text-xl font-semibold text-gray-300 mb-2">{{ t('settlementsView.empty.title') }}</h3>
      <p class="text-gray-500">
        {{ activeFilter === 'all' ? t('settlementsView.empty.all') : t('settlementsView.empty.withStatus', { status: activeFilter }) }}
      </p>
    </div>

    <!-- Settlement Cards -->
    <div v-else class="space-y-4">
      <div
        v-for="s in filteredSettlements"
        :key="s.id"
        class="bg-gray-800 rounded-lg border transition-all hover:border-gray-600 overflow-hidden"
        :class="statusBorderColor(s.status)"
      >
        <!-- Card Header -->
        <div class="flex items-center justify-between px-6 py-4 border-b border-gray-700/50">
          <div class="flex items-center gap-3">
            <span class="text-lg">{{ statusIcon(s.status) }}</span>
            <div>
              <!-- SF4: clickable dispute link -->
              <router-link
                :to="`/disputes#dispute-${s.dispute_id}`"
                class="font-semibold text-white hover:text-cyan-400 transition-colors"
                :title="t('settlementsView.disputeLinkTitle', { id: s.dispute_id })"
              >
                {{ t('settlementsView.disputePrefix') }} #{{ s.dispute_id }} →
              </router-link>
              <span
                :class="['ml-3 px-2 py-0.5 rounded-sm text-xs font-medium', statusBadgeClass(s.status)]"
              >
                {{ s.status }}
              </span>
              <span
                v-if="s.is_partial"
                class="ml-2 px-2 py-0.5 rounded-sm text-xs font-medium bg-yellow-900/50 text-yellow-400 border border-yellow-700"
              >
                {{ t('settlementsView.partial') }}
              </span>
              <!-- SF2: saga state pill (in-flight states only) -->
              <span
                v-if="sagaPillLabel(s)"
                class="ml-2 px-2 py-0.5 rounded-sm text-xs font-medium bg-blue-900/40 text-blue-300 border border-blue-700"
                :title="`saga_state=${s.saga_state}, retries=${s.saga_retry_count ?? 0}`"
              >
                {{ t('settlementsView.sagaPrefix') }} {{ sagaPillLabel(s) }}
              </span>
              <span
                v-if="sagaIsStuck(s)"
                class="ml-2 px-2 py-0.5 rounded-sm text-xs font-medium bg-amber-900/50 text-amber-300 border border-amber-700"
                :title="`saga_timeout_at=${s.saga_timeout_at}`"
              >
                <svg class="stl-warn-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.6 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.6a2 2 0 0 0-3.4 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg> {{ t('settlementsView.stuck') }}
              </span>
            </div>
          </div>
          <div class="text-sm text-gray-500">
            {{ formatDate(s.requested_at) }}
          </div>
        </div>

        <!-- Card Body -->
        <div class="px-6 py-4 grid grid-cols-1 md:grid-cols-3 gap-6">
          <!-- Parties -->
          <div>
            <div class="text-xs text-gray-500 uppercase tracking-wider mb-2">{{ t('settlementsView.parties') }}</div>
            <div class="space-y-2">
              <div class="flex items-center gap-2">
                <span class="text-green-400 text-xs">▲ {{ t('settlementsView.complainant') }}</span>
                <code class="text-xs text-gray-300 bg-gray-900 px-2 py-0.5 rounded-sm truncate max-w-[200px]">
                  {{ truncateDid(s.complainant_did) }}
                </code>
              </div>
              <div class="flex items-center gap-2">
                <span class="text-red-400 text-xs">▼ {{ t('settlementsView.defendant') }}</span>
                <code class="text-xs text-gray-300 bg-gray-900 px-2 py-0.5 rounded-sm truncate max-w-[200px]">
                  {{ truncateDid(s.defendant_did) }}
                </code>
              </div>
            </div>
          </div>

          <!-- Amounts, each in its own frame's unit -->
          <div>
            <div class="text-xs text-gray-500 uppercase tracking-wider mb-2">{{ t('settlementsView.avtFlow') }}</div>
            <div class="space-y-1">
              <div class="flex justify-between">
                <span class="text-gray-400 text-sm">{{ t('settlementsView.stats.requested') }}:</span>
                <span class="text-white font-medium">{{ s.requested_amount }} {{ defendantUnit(s) }}</span>
              </div>
              <div class="flex justify-between">
                <span class="text-gray-400 text-sm">{{ t('settlementsView.stats.slashed') }}:</span>
                <span :class="s.slashed_amount > 0 ? 'text-red-400 font-medium' : 'text-gray-600'">
                  {{ s.slashed_amount }} {{ defendantUnit(s) }}
                </span>
              </div>
              <div class="flex justify-between">
                <span class="text-gray-400 text-sm">{{ t('settlementsView.stats.minted') }}:</span>
                <span :class="s.minted_amount > 0 ? 'text-green-400 font-medium' : 'text-gray-600'">
                  {{ s.minted_amount }} {{ originUnit(s) }}
                </span>
              </div>
              <div class="flex justify-between" v-if="s.shortfall > 0">
                <span class="text-yellow-400 text-sm">{{ t('settlementsView.shortfall') }}:</span>
                <span class="text-yellow-400 font-medium">{{ s.shortfall }} {{ defendantUnit(s) }}</span>
              </div>
            </div>
          </div>

          <!-- Timeline -->
          <div>
            <div class="text-xs text-gray-500 uppercase tracking-wider mb-2">{{ t('settlementsView.timeline') }}</div>
            <div class="space-y-1 text-sm">
              <div class="flex items-center gap-2">
                <span class="w-2 h-2 rounded-full bg-cyan-400"></span>
                <span class="text-gray-400">{{ t('settlementsView.stats.requested') }}:</span>
                <span class="text-gray-300">{{ formatTime(s.requested_at) }}</span>
              </div>
              <div class="flex items-center gap-2" v-if="s.slashed_at">
                <span class="w-2 h-2 rounded-full bg-red-400"></span>
                <span class="text-gray-400">{{ t('settlementsView.stats.slashed') }}:</span>
                <span class="text-gray-300">{{ formatTime(s.slashed_at) }}</span>
              </div>
              <div class="flex items-center gap-2" v-if="s.settled_at">
                <span class="w-2 h-2 rounded-full bg-green-400"></span>
                <span class="text-gray-400">{{ t('settlementsView.stats.settled') }}:</span>
                <span class="text-gray-300">{{ formatTime(s.settled_at) }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Error Message -->
        <div
          v-if="s.error_message"
          class="px-6 py-3 bg-gray-900/50 border-t border-gray-700/50"
        >
          <p class="text-xs text-gray-500">
            <span class="text-yellow-500"><svg class="stl-warn-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.6 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.6a2 2 0 0 0-3.4 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg></span> {{ s.error_message }}
          </p>
        </div>

        <!-- Admin Approve/Reject for PENDING_ADMIN_APPROVAL -->
        <div
          v-if="s.status === 'PENDING_ADMIN_APPROVAL'"
          class="px-6 py-3 bg-yellow-900/20 border-t border-yellow-700/30 flex items-center gap-4"
        >
          <span class="text-sm text-yellow-400 font-medium"><svg class="stl-warn-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.6 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.6a2 2 0 0 0-3.4 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg> {{ t('settlementsView.requiresAdmin') }}</span>
          <div class="ml-auto flex gap-2">
            <button
              @click="openDecision('approve', s.id)"
              class="px-4 py-1.5 bg-green-600 hover:bg-green-500 text-white text-sm font-medium rounded-lg transition-all"
              :disabled="approving === s.id"
            >
              {{ approving === s.id ? t('settlementsView.approving') : '✓ ' + t('settlementsView.approveSlash') }}
            </button>
            <button
              @click="openDecision('reject', s.id)"
              class="px-4 py-1.5 bg-red-700 hover:bg-red-600 text-white text-sm font-medium rounded-lg transition-all"
              :disabled="approving === s.id"
            >
              ✗ {{ t('settlementsView.reject') }}
            </button>
          </div>
        </div>

        <!-- Transaction IDs -->
        <div
          v-if="s.slash_tx_id || s.mint_tx_id"
          class="px-6 py-3 bg-gray-900/30 border-t border-gray-700/30 flex gap-6"
        >
          <div v-if="s.slash_tx_id" class="text-xs">
            <span class="text-gray-500">{{ t('settlementsView.slashTx') }}:</span>
            <code class="text-gray-400 ml-1">{{ s.slash_tx_id }}</code>
          </div>
          <div v-if="s.mint_tx_id" class="text-xs">
            <span class="text-gray-500">{{ t('settlementsView.mintTx') }}:</span>
            <code class="text-gray-400 ml-1">{{ s.mint_tx_id }}</code>
          </div>
        </div>
      </div>
    </div>

    <!-- Error Alert -->
    <div v-if="error" class="mt-6 bg-red-900/30 border border-red-700 rounded-lg p-4">
      <p class="text-red-400">{{ error }}</p>
    </div>

    </div><!-- /.stl-content -->

    <!-- S15 / SF9: Decision modal — admin approve/reject with optional reason -->
    <Teleport to="body">
      <div
        v-if="decisionModal.open"
        class="fixed inset-0 z-9800 flex items-center justify-center bg-black/70"
        @click.self="closeDecision"
      >
        <div class="bg-gray-900 border border-gray-700 rounded-lg p-6 w-[min(480px,96vw)]">
          <h3 class="text-lg font-semibold text-white mb-2">
            {{ decisionModal.action === 'approve' ? t('settlementsView.decision.approveTitle') : t('settlementsView.decision.rejectTitle') }}
          </h3>
          <p class="text-sm text-gray-400 mb-4">
            <template v-if="decisionModal.action === 'approve'">
              {{ t('settlementsView.decision.approveBody') }}
            </template>
            <template v-else>
              {{ t('settlementsView.decision.rejectBody') }}
            </template>
            {{ t('settlementsView.decision.settlementLabel') }}: <code class="text-cyan-400">{{ decisionModal.settlementId }}</code>
          </p>
          <label class="block text-xs text-gray-400 uppercase tracking-wider mb-1">
            {{ t('settlementsView.decision.reasonLabel') }}
          </label>
          <textarea
            v-model="decisionModal.reason"
            rows="3"
            maxlength="500"
            class="w-full bg-gray-800 border border-gray-600 rounded-sm px-3 py-2 text-white text-sm focus:outline-hidden focus:border-cyan-500"
            :placeholder="t('settlementsView.decision.reasonPlaceholder')"
          />
          <div class="flex justify-end gap-3 mt-4">
            <button
              @click="closeDecision"
              class="px-4 py-2 rounded-sm bg-gray-700 text-gray-300 hover:bg-gray-600 text-sm"
            >
              {{ t('settlementsView.decision.cancel') }}
            </button>
            <button
              @click="confirmDecision"
              :disabled="approving === decisionModal.settlementId"
              :class="[
                'px-4 py-2 rounded-sm text-white text-sm font-medium',
                decisionModal.action === 'approve'
                  ? 'bg-green-600 hover:bg-green-500'
                  : 'bg-red-700 hover:bg-red-600',
                approving === decisionModal.settlementId ? 'opacity-60 cursor-not-allowed' : ''
              ]"
            >
              {{ approving === decisionModal.settlementId
                ? t('settlementsView.decision.working')
                : (decisionModal.action === 'approve' ? '✓ ' + t('settlementsView.decision.confirmApproval') : '✗ ' + t('settlementsView.decision.confirmRejection')) }}
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
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { ref, computed, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useSettlementsStore } from '@/stores/settlements'
import type { Settlement, PeerSlashConfig as PeerConfig } from '@/services/api/settlements'
import { useI18n } from '@/composables/useI18n'
import { useCurrency } from '@/composables/useCurrency'
import { useFrameManifest } from '@/composables/useFrameManifest'
import { settlementUnit } from '@/services/frameManifest'

const { t } = useI18n()
const { localCurrency } = useCurrency()

// A settlement's amounts are in two frames' units: the slash (and the requested amount and shortfall it is measured
// against) in the defendant frame's, the compensation in the origin's, whose treasury pays it. Each is named from the
// party's own frame (its DID's issuer, else its registry URL); an unknown one names no unit, never another frame's.
// The backend pays the same number it slashed, without FX, so a card can read "10 SBXB slashed, 10 SBXA paid".
const frameManifest = useFrameManifest()
function defendantUnit(s: Settlement): string {
  return settlementUnit(frameManifest.manifest.value, s.defendant_did, s.defendant_registry_url) ?? ''
}
function originUnit(s: Settlement): string {
  return settlementUnit(frameManifest.manifest.value, s.complainant_did, s.origin_registry_url) ?? ''
}

const settlementsStore = useSettlementsStore()
const {
  settlements,
  stats,
  peerConfigs,
  loading,
  error,
  listFailed,
  peerConfigError,
  filter: activeFilter,
  filteredSettlements,
  stuckSagas,
} = storeToRefs(settlementsStore)

const approving = ref<string | null>(null)
// 2026-05-08: collapse per-peer thresholds by default — section was
// taking the whole page when many peers were configured.
const peerConfigsExpanded = ref(false)

// Approve/reject modal (S15 — admin reason capture)
const decisionModal = ref<{
  open: boolean
  action: 'approve' | 'reject' | null
  settlementId: string | null
  reason: string
}>({ open: false, action: null, settlementId: null, reason: '' })

const filters = computed(() => [
  { label: t('settlementsView.filters.all'), value: 'all' as const },
  { label: t('settlementsView.filters.pending'), value: 'pending' as const },
  { label: t('settlementsView.filters.settled'), value: 'settled' as const },
  { label: t('settlementsView.filters.failed'), value: 'failed' as const },
])

// §2026-06-07 v2k — no-emoji rule: monochrome typographic marks (inherit the
// status text color) instead of colored emoji. (Commander)
function statusIcon(status: string): string {
  const icons: Record<string, string> = {
    PENDING_ADMIN_APPROVAL: '○',
    PENDING_SLASH: '◔',
    SLASHING: '◆',
    SLASHED: '●',
    SETTLED: '✓',
    FAILED: '✕',
    REJECTED: '⊘',
    EXPIRED: '◌',
  }
  return icons[status] || '·'
}

function statusBorderColor(status: string): string {
  const colors: Record<string, string> = {
    PENDING_ADMIN_APPROVAL: 'border-amber-600/50',
    PENDING_SLASH: 'border-yellow-700/40',
    SLASHING: 'border-orange-700/40',
    SLASHED: 'border-blue-700/40',
    SETTLED: 'border-green-700/40',
    FAILED: 'border-red-700/40',
    REJECTED: 'border-red-800/40',
    EXPIRED: 'border-gray-600',
  }
  return colors[status] || 'border-gray-700'
}

function statusBadgeClass(status: string): string {
  const classes: Record<string, string> = {
    PENDING_ADMIN_APPROVAL: 'bg-amber-900/50 text-amber-400 border border-amber-700',
    PENDING_SLASH: 'bg-yellow-900/50 text-yellow-400 border border-yellow-700',
    SLASHING: 'bg-orange-900/50 text-orange-400 border border-orange-700',
    SLASHED: 'bg-blue-900/50 text-blue-400 border border-blue-700',
    SETTLED: 'bg-green-900/50 text-green-400 border border-green-700',
    FAILED: 'bg-red-900/50 text-red-400 border border-red-700',
    REJECTED: 'bg-red-900/50 text-red-300 border border-red-800',
    EXPIRED: 'bg-gray-700/50 text-gray-400 border border-gray-600',
  }
  return classes[status] || 'bg-gray-700 text-gray-400'
}

function truncateDid(did: string): string {
  if (!did) return '—'
  if (did.length <= 24) return did
  return did.slice(0, 16) + '...' + did.slice(-8)
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(appLocale(), {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString(appLocale(), {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

// SF6+SF7+S15: thin wrappers that delegate to the store + open the reason modal
function openDecision(action: 'approve' | 'reject', settlementId: string) {
  decisionModal.value = { open: true, action, settlementId, reason: '' }
}

function closeDecision() {
  decisionModal.value = { open: false, action: null, settlementId: null, reason: '' }
}

async function confirmDecision() {
  const m = decisionModal.value
  if (!m.action || !m.settlementId) return
  approving.value = m.settlementId
  try {
    if (m.action === 'approve') {
      await settlementsStore.approve(m.settlementId, m.reason || undefined)
    } else {
      await settlementsStore.reject(m.settlementId, m.reason || undefined)
    }
    closeDecision()
  } catch (e: any) {
    // store has set error.value already
  } finally {
    approving.value = null
  }
}

function setActiveFilter(f: 'all' | 'pending' | 'settled' | 'failed') {
  settlementsStore.setFilter(f)
}

async function refresh() {
  await Promise.all([
    settlementsStore.fetchSettlements(),
    settlementsStore.fetchPeerConfigs(),
  ])
}

// §FESUITE 134 (2026-10-15): a refused write leaves the control where the registry holds it and says so here
const peerWriteFailed = ref(false)
async function togglePeerAutoSlash(peer: PeerConfig, ev: Event) {
  peerWriteFailed.value = !(await settlementsStore.togglePeerAutoSlash(peer))
  ;(ev.target as HTMLInputElement).checked = !!peer.auto_slash_enabled
}

async function updatePeerThreshold(peer: PeerConfig, ev: Event) {
  const box = ev.target as HTMLInputElement
  peerWriteFailed.value = !(await settlementsStore.updatePeerThreshold(peer, box.value))
  box.value = String(peer.auto_slash_max_avt ?? 0)
}

// SF2: human-readable saga state for the per-card pill
function sagaPillLabel(s: Settlement): string | null {
  const st = s.saga_state
  if (!st || st === 'LEGACY') return null
  if (st === 'FINALIZED' || st === 'ROLLED_BACK') return null
  return st.replace(/_/g, ' ').toLowerCase()
}

function sagaIsStuck(s: Settlement): boolean {
  if (!s.saga_timeout_at) return false
  const terminal = ['SETTLED', 'EXPIRED', 'REJECTED', 'FAILED'].includes(s.status)
  if (terminal) return false
  return new Date(s.saga_timeout_at).getTime() < Date.now()
}

onMounted(() => {
  refresh()
})
</script>

<style scoped>
/* ── Theme tokens (mirrors AdminCanaries Phase 11 polish, 2026-05-06) ─────
   Brand-mapped accent so 'neural'/'sovereign' theme switches propagate.
   Semantic status colors stay fixed across themes.
*/
.settlements-view {
  --stl-cyan:     var(--nc-primary, #00d2d2);
  --stl-cyan-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --stl-success:  var(--nc-success, #00ff88);
  --stl-warning:  var(--nc-warning, #ff9500);
  --stl-danger:   var(--nc-danger,  #ff3366);
  --stl-purple:   #b87aff;
  --stl-mono:     'IBM Plex Mono', 'Fira Code', monospace;

  --stl-surface:   var(--nc-deep,    #0a0d16);
  --stl-surface-2: var(--nc-surface, #111827);
  --stl-border:    rgba(var(--stl-cyan-rgb), 0.18);
  --stl-text-bright: var(--nc-text-primary, #e8eaed);
  --stl-text-muted:  var(--nc-text-muted,   #6b7785);

  position: relative;
  min-height: 100vh;
  padding: 0 0 32px 0;
  /* §pass9 (2026-05-15): transparent background so DashboardLayout's
     global ViewAmbient (violet + theme-accent glows + grid + scan) shows
     through. Previously a solid --stl-surface dark colour covered it,
     leaving the page looking grey. Per feedback_view_ambient_lives_in_layout. */
  background: transparent;
  color: var(--stl-text-bright);
  transition: background 240ms ease, color 240ms ease;
}

/* ── Ambient background ─────────────────────────────────────────────────── */
.stl-ambient {
  position: fixed; inset: 0; z-index: 0; pointer-events: none; overflow: hidden;
}
.stl-grid {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(var(--stl-cyan-rgb), 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--stl-cyan-rgb), 0.03) 1px, transparent 1px);
  background-size: 60px 60px;
  /* §DESKCHROME 2026-08-28: grid is STATIC — perpetual drift removed (Commander) */
}
.stl-scan {
  position: absolute; inset: 0;
  background: repeating-linear-gradient(
    180deg,
    transparent 0, transparent 3px,
    rgba(var(--stl-cyan-rgb), 0.025) 3px, rgba(var(--stl-cyan-rgb), 0.025) 4px
  );
}
.stl-glow {
  position: absolute; border-radius: 50%; filter: blur(120px); opacity: 0.18;
}
.stl-glow-1 { width: 480px; height: 480px; background: rgba(var(--stl-cyan-rgb), 0.6); top: -100px; right: -100px; }
.stl-glow-2 { width: 360px; height: 360px; background: rgba(184, 122, 255, 0.4); bottom: -80px; left: -80px; }

/* ── Hero strip ─────────────────────────────────────────────────────────── */
.stl-hero {
  position: relative; z-index: 1;
  padding: 48px 32px 24px;
}
.stl-hero-inner { max-width: 1200px; margin: 0 auto; }
.stl-chip-hero {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--stl-mono); font-size: 10px; font-weight: 600;
  letter-spacing: 0.18em; color: var(--stl-cyan);
  padding: 4px 12px;
  border: 1px solid rgba(var(--stl-cyan-rgb), 0.25);
  border-radius: 99px; margin-bottom: 14px;
  background: rgba(var(--stl-cyan-rgb), 0.04);
}
.stl-chip-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--stl-cyan);
  box-shadow: 0 0 8px var(--stl-cyan);
  animation: stlPulse 1.6s ease-in-out infinite;
}
@keyframes stlPulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
.stl-h1 {
  font-family: 'Orbitron', 'IBM Plex Sans', sans-serif;
  font-weight: 800; font-size: 34px; letter-spacing: 0.02em;
  margin: 0 0 10px; color: var(--stl-text-bright); line-height: 1.15;
}
.stl-accent { color: var(--stl-cyan); text-shadow: 0 0 14px rgba(var(--stl-cyan-rgb), 0.45); }
.stl-lead { color: var(--stl-text-muted); font-size: 14px; max-width: 760px; line-height: 1.7; margin: 0; }

/* Content area renders above ambient layer */
.stl-content {
  position: relative; z-index: 1;
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 32px;
}

/* Tailwind utility overrides — re-route to nc palette */
.settlements-view [class*="bg-gray-800"] {
  background-color: var(--stl-surface-2) !important;
}
.settlements-view [class*="bg-gray-900"] {
  background-color: rgba(0, 0, 0, 0.35) !important;
}
.settlements-view [class*="border-gray-700"] {
  border-color: var(--stl-border) !important;
}
.settlements-view .text-cyan-400,
.settlements-view .text-cyan-600 {
  color: var(--stl-cyan) !important;
}
.settlements-view .text-gray-400 {
  color: var(--stl-text-muted) !important;
}
.settlements-view input[type="number"],
.settlements-view input[type="checkbox"] {
  background-color: var(--stl-surface-2);
  border-color: rgba(var(--stl-cyan-rgb), 0.25);
  color: var(--stl-text-bright);
}

/* Stat cards — give them the canary hover lift */
.settlements-view .grid > .bg-gray-800 {
  transition: border-color 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease;
}
.settlements-view .grid > .bg-gray-800:hover {
  border-color: rgba(var(--stl-cyan-rgb), 0.35) !important;
  transform: translateY(-1px);
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.35);
}

/* Settlement card: subtle accent line on top */
.settlements-view .space-y-4 > div.bg-gray-800 {
  position: relative;
  overflow: hidden;
}
.settlements-view .space-y-4 > div.bg-gray-800::before {
  content: '';
  position: absolute; left: 0; right: 0; top: 0; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(var(--stl-cyan-rgb), 0.4), transparent);
}

/* §2026-06-07 v2j — DESIGN-LANGUAGE: de-grey the legacy Tailwind grey surfaces.
   Scoped `.settlements-view :is(...)` (0,2,0) beats the bare utilities (0,1,0) →
   no !important. bg-gray-800 → house tint; bg-gray-900 stays a touch deeper to
   keep nesting hierarchy; grey borders → house hairline. Ref:
   PRODUCTION_DOCS/03_SERVICES/Frontend/Design_Language.md. (Commander) */
.settlements-view :is(.bg-gray-800, .bg-gray-900) {
  background:
    linear-gradient(168deg, rgba(255,255,255,0.09), rgba(255,255,255,0.025) 46%, rgba(255,255,255,0.004) 100%),
    rgba(10, 14, 24, 0.45);
  backdrop-filter: blur(16px) saturate(1.12);
  -webkit-backdrop-filter: blur(16px) saturate(1.12);
}
.settlements-view .bg-gray-900 {
  background:
    linear-gradient(168deg, rgba(255,255,255,0.05), rgba(255,255,255,0.012) 50%, rgba(255,255,255,0) 100%),
    rgba(4, 7, 14, 0.5);
}
.settlements-view :is(.border-gray-700, .border-gray-600) { border-color: rgba(var(--stl-cyan-rgb), 0.24); }
/* card-sized surfaces get rounder corners + a clear elevation shadow */
.settlements-view .rounded-lg:is(.bg-gray-800, .bg-gray-900) {
  border-radius: 14px;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.08), 0 20px 46px -24px rgba(0,0,0,0.95);
}
/* §2026-06-07 v2k — inline warning icon replacing the <Icon name="mdi:alert" /> emoji (inherits color/size) */
.stl-warn-ic { width: 1em; height: 1em; display: inline-block; vertical-align: -0.15em; flex-shrink: 0; }
/* ═══ §v0003 polish (2 passes) ═══ */
/* pass 1 — hero stat numbers: tabular + per-value glow (inherits the Tailwind text color) */
.settlements-view :is(.text-2xl, .text-xl).font-bold { font-variant-numeric: tabular-nums; letter-spacing: -0.01em; text-shadow: 0 0 16px color-mix(in srgb, currentColor 20%, transparent); }
/* pass 2 — keyboard focus ring */
.settlements-view :is(button, input, select, [tabindex]):focus-visible { outline: 2px solid rgba(var(--stl-cyan-rgb), 0.55); outline-offset: 2px; border-radius: 6px; }
</style>
