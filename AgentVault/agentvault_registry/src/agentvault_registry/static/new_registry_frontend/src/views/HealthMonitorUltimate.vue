<template>
  <div class="hm-module">

    <!-- ── Header ─────────────────────────────────────────────────────── -->
    <div class="hm-header">
      <div class="hm-header-left">
        <div class="hm-header-icon">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 12h4l3-9 4 18 3-9h4"/>
          </svg>
        </div>
        <div>
          <div class="hm-header-title">{{ t('healthMonitorView.title') }}</div>
          <div class="hm-header-sub">Sovereign infrastructure observability — dev + agent endpoints</div>
        </div>
      </div>
      <div class="hm-header-right">
        <!-- §FESUITE (V0578): each figure waits for its own read and reads "—" until it answered (and after it failed). The
             score drew a red "0%" before the first check, the alerts a green "0" over a failed Prometheus read, and the
             uptime was the literal 99.9%: nothing on this page reads an uptime, so that tile is gone. -->
        <div class="hm-quickstat">
          <span class="hm-quickstat-label">Score</span>
          <div class="hm-quickstat-value" :class="checkAnswered ? scoreColorClass : ''" data-testid="hm-score">{{ checkAnswered ? Math.round(overallHealth) + '%' : '—' }}</div>
        </div>
        <div class="hm-quickstat">
          <span class="hm-quickstat-label">Services</span>
          <div class="hm-quickstat-value" data-testid="hm-services">{{ checkAnswered ? healthyServices + '/' + totalServices : '—' }}</div>
        </div>
        <div class="hm-quickstat">
          <span class="hm-quickstat-label">Alerts</span>
          <div class="hm-quickstat-value" :class="alertsAnswered ? (firingAlertCount > 0 ? 'red' : 'green') : ''" data-testid="hm-alerts">{{ alertsAnswered ? firingAlertCount : '—' }}</div>
        </div>
        <button class="hm-btn hm-btn-ghost hm-btn-sm" @click="exportReport">
          ↓ Export
        </button>
      </div>
    </div>

    <!-- ── Tab Bar ────────────────────────────────────────────────────── -->
    <div class="hm-tabs">
      <button v-for="tab in tabs" :key="tab.id" class="hm-tab" :class="{ active: activeTab === tab.id }" @click="activeTab = tab.id">
        {{ tab.label }}
        <span v-if="tab.id === 'prometheus' && firingAlertCount > 0" class="hm-tab-badge hm-tab-badge-red">{{ firingAlertCount }}</span>
      </button>
    </div>

    <!-- ── Tab Content ────────────────────────────────────────────────── -->
    <div class="hm-content">

      <!-- ══ OVERVIEW ══════════════════════════════════════════════════ -->
      <div v-if="activeTab === 'overview'" style="display:flex;flex-direction:column;gap:20px;">

        <!-- Agent Auth Warning Banner -->
        <div v-if="!hasAgentAuth" class="hm-agent-auth-banner">
          <div class="hm-agent-auth-banner-inner">
            <div class="hm-agent-auth-icon">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12,1L3,5V11C3,16.55 6.84,21.74 12,23C17.16,21.74 21,16.55 21,11V5L12,1Z"/>
                <rect x="10" y="9" width="4" height="5" rx="0.5"/>
                <circle cx="12" cy="7.5" r="1.5"/>
              </svg>
            </div>
            <div class="hm-agent-auth-text">
              <div class="hm-agent-auth-title">{{ t('healthMonitorView.authTitle') }}</div>
              <div class="hm-agent-auth-desc">
                Agent-authenticated endpoints are excluded from this scan. The health score shown
                (typically ~72%) reflects only developer and public endpoints. To get a full 100%
                health assessment, activate an agent with credentials via the Agent Selector in the
                top bar. Agent auth is required for TEG transfer, lock, governance, and dispute
                endpoints.
              </div>
            </div>
          </div>
        </div>

        <!-- Health Score + Controls -->
        <div class="hm-card hm-card-accent">
          <div class="hm-card-header">
            <span class="hm-card-title">{{ t('healthMonitorView.cards.healthScore') }}</span>
            <div class="hm-refresh-bar">
              <label class="hm-refresh-label">
                <input type="checkbox" v-model="autoRefresh" @change="toggleAutoRefresh">
                Auto
              </label>
              <select aria-label="Refresh interval" v-model="refreshInterval" @change="updateRefreshInterval" class="hm-select">
                <option :value="15000">15s</option>
                <option :value="30000">30s</option>
                <option :value="60000">1m</option>
                <option :value="300000">5m</option>
              </select>
              <span v-if="autoRefresh" style="font-family:var(--hm-font-mono);font-size:9px;color:var(--hm-text-muted);">in {{ nextRefreshIn }}s</span>
              <button class="hm-btn hm-btn-primary hm-btn-sm" @click="runHealthCheck" :disabled="loading">
                <span v-if="loading" style="display:inline-block;animation:spin 1s linear infinite;">⟳</span>
                <span v-else>⟳</span>
                {{ loading ? 'Checking...' : 'Check Now' }}
              </button>
            </div>
          </div>
          <ReadFailedNotice v-if="checkFailed" dense data-testid="hm-check-failed" :retry="runHealthCheck"
            :text="checkAnswered ? 'The latest health check failed. The figures below are from the last check that answered.' : 'The health check could not be read. Nothing below has been measured yet.'" />
          <div class="hm-card-body" style="display:flex;gap:32px;align-items:flex-start;flex-wrap:wrap;">
            <!-- Donut -->
            <div class="hm-donut-container">
              <svg class="hm-donut-svg" viewBox="0 0 160 160">
                <circle cx="80" cy="80" r="68" fill="none" stroke="rgba(var(--nc-primary-rgb),0.08)" stroke-width="10"/>
                <circle cx="80" cy="80" r="68"
                  fill="none"
                  :stroke="checkAnswered ? scoreColor : 'transparent'"
                  stroke-width="10"
                  stroke-linecap="round"
                  :stroke-dasharray="`${overallHealth * 4.27} 427`"
                  transform="rotate(-90 80 80)"
                  style="transition:stroke-dasharray 0.8s ease, stroke 0.5s ease;"
                />
              </svg>
              <div class="hm-donut-center">
                <div class="hm-donut-pct" :style="{ color: checkAnswered ? scoreColor : 'var(--hm-text-muted)' }">{{ checkAnswered ? Math.round(overallHealth) + '%' : '—' }}</div>
                <div class="hm-donut-status">{{ checkAnswered ? getHealthStatus(overallHealth) : '' }}</div>
              </div>
            </div>
            <!-- Details -->
            <div style="flex:1;min-width:200px;">
              <div style="display:flex;flex-direction:column;gap:0;">
                <div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid rgba(var(--nc-primary-rgb),0.06);font-size:12px;">
                  <span style="color:var(--hm-text-dim);">Last check</span>
                  <span style="font-family:var(--hm-font-mono);font-size:11px;color:var(--hm-text);">{{ formatTime(lastCheckTime) }}</span>
                </div>
                <div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid rgba(var(--nc-primary-rgb),0.06);font-size:12px;">
                  <span style="color:var(--hm-text-dim);">Avg response</span>
                  <span style="font-family:var(--hm-font-mono);font-size:11px;" :style="{ color: checkAnswered && avgResponseTime > 800 ? 'var(--hm-yellow)' : 'var(--hm-text)' }">{{ checkAnswered ? avgResponseTime + 'ms' : '—' }}</span>
                </div>
                <div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid rgba(var(--nc-primary-rgb),0.06);font-size:12px;">
                  <span style="color:var(--hm-text-dim);">Dev endpoints</span>
                  <span style="font-family:var(--hm-font-mono);font-size:11px;" :style="{ color: checkAnswered ? 'var(--hm-green)' : 'var(--hm-text-muted)' }" data-testid="hm-dev-endpoints">{{ checkAnswered ? devEndpointsHealthy + '/' + devEndpointsTotal + ' healthy' : '—' }}</span>
                </div>
                <div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid rgba(var(--nc-primary-rgb),0.06);font-size:12px;">
                  <span style="color:var(--hm-text-dim);">Agent endpoints</span>
                  <span v-if="hasAgentAuth" style="font-family:var(--hm-font-mono);font-size:11px;color:var(--hm-cyan);">{{ checkAnswered ? agentEndpointsHealthy + '/' + agentEndpointsTotal + ' healthy' : '—' }}</span>
                  <span v-else style="font-family:var(--hm-font-mono);font-size:11px;color:var(--hm-text-muted);" :title="agentEndpointsNA + ' agent-only checks skipped — sign in an agent to test them'">N/A{{ checkAnswered ? ' · ' + agentEndpointsNA + ' skipped' : '' }}</span>
                </div>
                <div style="display:flex;justify-content:space-between;padding:7px 0;font-size:12px;">
                  <span style="color:var(--hm-text-dim);">Public endpoints</span>
                  <span style="font-family:var(--hm-font-mono);font-size:11px;color:var(--hm-text);">{{ checkAnswered ? pubEndpointsHealthy + '/' + pubEndpointsTotal + ' healthy' : '—' }}</span>
                </div>
              </div>
              <div style="margin-top:12px;padding:8px 10px;border-radius:6px;background:rgba(var(--nc-primary-rgb),0.05);border:1px solid rgba(var(--nc-primary-rgb),0.12);font-family:var(--hm-font-mono);font-size:9px;color:var(--hm-text-dim);letter-spacing:0.04em;">
                System health = public + developer endpoints{{ hasAgentAuth ? ' + agent endpoints' : '' }}. Agent-only checks are skipped (N/A, not failed) when no agent is signed in.
              </div>
            </div>
            <!-- Network Snapshot -->
            <div style="display:flex;flex-direction:column;gap:8px;min-width:180px;">
              <div style="font-family:var(--hm-font-mono);font-size:9px;letter-spacing:0.1em;text-transform:uppercase;color:var(--hm-text-muted);margin-bottom:4px;">Network Snapshot</div>
              <ReadFailedNotice v-if="networkRead === 'failed'" dense data-testid="hm-network-failed"
                text="The network snapshot could not be read just now." :retry="fetchNetworkMetrics" />
              <div class="hm-stat-tile">
                <span class="tile-label">Active Agents</span>
                <span class="tile-value" data-testid="hm-active-agents">{{ netOk ? networkMetrics.activeAgents : '—' }}</span>
                <span class="tile-sub">of {{ netOk ? networkMetrics.totalAgents : '—' }} registered</span>
              </div>
              <div class="hm-stat-tile">
                <span class="tile-label">P50 Latency</span>
                <span class="tile-value" style="font-size:16px;">{{ netOk ? networkMetrics.p50 + 'ms' : '—' }}</span>
                <span class="tile-sub">P95: {{ netOk ? networkMetrics.p95 + 'ms' : '—' }}</span>
              </div>
              <div class="hm-stat-tile">
                <span class="tile-label">Error Rate</span>
                <span class="tile-value" data-testid="hm-error-rate" :style="{ color: !netOk ? 'var(--hm-text-muted)' : networkMetrics.errorRate > 0.01 ? 'var(--hm-yellow)' : 'var(--hm-green)', fontSize:'16px' }">{{ netOk ? (networkMetrics.errorRate * 100).toFixed(2) + '%' : '—' }}</span>
                <span class="tile-sub">last window</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Service Matrix -->
        <div class="hm-card">
          <div class="hm-card-header">
            <span class="hm-card-title">{{ t('healthMonitorView.cards.serviceMatrix') }}</span>
            <span style="font-family:var(--hm-font-mono);font-size:9px;color:var(--hm-text-muted);">{{ checkAnswered ? healthyServices + ' / ' + totalServices + ' healthy' : '' }}</span>
          </div>
          <div class="hm-card-body">
            <ReadFailedNotice v-if="checkFailed && Object.keys(serviceGroups).length === 0" dense data-testid="hm-matrix-failed"
              text="The health check could not be read, so no service is shown." />
            <div v-else-if="Object.keys(serviceGroups).length === 0" class="hm-empty">
              <div class="hm-empty-icon"><Icon name="mdi:radio-tower" /></div>
              <div class="hm-empty-title">No data yet</div>
              <div class="hm-empty-sub">{{ loading ? 'Checking…' : 'Run a health check to populate.' }}</div>
            </div>
            <div v-else style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;">
              <div v-for="(group, name) in serviceGroups" :key="name"
                class="hm-service-card"
                :class="getScoreClass(group.health)">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">
                  <span style="font-size:18px;">{{ group.icon }}</span>
                  <span class="hm-service-name">{{ group.label }}</span>
                  <span class="hm-service-pct" :class="getScoreClass(group.health)">{{ group.health }}%</span>
                </div>
                <div style="margin-bottom:8px;">
                  <div class="hm-progress"><div class="hm-progress-fill" :class="getProgressColor(group.health)" :style="{ width: group.health + '%' }"></div></div>
                </div>
                <div style="display:flex;flex-direction:column;gap:3px;">
                  <div v-for="ep in group.endpoints" :key="ep.path"
                    class="hm-endpoint-row"
                    :class="ep.authRequired === 'agent' && ep.statusCode === 401 ? 'agent-skip' : (ep.healthy ? 'healthy' : 'unhealthy')">
                    <span class="hm-method">{{ ep.method }}</span>
                    <span class="hm-path">{{ ep.path }}</span>
                    <span v-if="ep.authRequired === 'agent' && ep.statusCode === 401" style="font-family:var(--hm-font-mono);font-size:9px;color:var(--hm-cyan-dim);">ℹ agent</span>
                    <span v-else class="hm-resp">{{ ep.responseTime }}ms</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

      </div>

      <!-- ══ TIMELINE ═══════════════════════════════════════════════════ -->
      <div v-if="activeTab === 'timeline'" style="display:flex;flex-direction:column;gap:20px;">
        <div class="hm-card">
          <div class="hm-card-header">
            <span class="hm-card-title">{{ t('healthMonitorView.cards.history') }}</span>
            <div style="display:flex;gap:6px;">
              <button v-for="r in timeRanges" :key="r.v"
                class="hm-btn hm-btn-sm"
                :class="selectedTimeRange === r.v ? 'hm-btn-primary' : 'hm-btn-ghost'"
                @click="selectedTimeRange = r.v">{{ r.l }}</button>
            </div>
          </div>
          <div class="hm-card-body">
            <div v-if="healthHistory.length === 0" class="hm-empty">
              <div class="hm-empty-icon"><Icon name="mdi:trending-up" /></div>
              <div class="hm-empty-title">No history yet</div>
              <div class="hm-empty-sub">Run a health check to begin tracking.</div>
            </div>
            <div v-else>
              <div class="hm-chart-wrap" style="margin-bottom:16px;">
                <canvas ref="healthChart"></canvas>
              </div>
              <div class="hm-chart-wrap" style="margin-bottom:16px;">
                <canvas ref="responseChart"></canvas>
              </div>
              <div style="overflow-x:auto;">
                <table class="hm-table" aria-label="Recent health check events">
                  <caption class="sr-only">Recent health check events with timestamps and status.</caption>
                  <thead>
                    <tr>
                      <th>Timestamp</th>
                      <th>Score</th>
                      <th>Services</th>
                      <th>Avg Response</th>
                      <th>Errors</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="e in filteredHistory" :key="e.timestamp">
                      <td class="mono">{{ formatTimestamp(e.timestamp) }}</td>
                      <td><span class="hm-hist-score" :class="getScoreClass(e.score)">{{ e.score }}%</span></td>
                      <td class="mono">{{ e.healthyServices }}/{{ e.totalServices }}</td>
                      <td class="mono">{{ e.avgResponseTime }}ms</td>
                      <td class="mono">{{ e.errorCount }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ══ INFRASTRUCTURE ═════════════════════════════════════════════ -->
      <div v-if="activeTab === 'infrastructure'" style="display:flex;flex-direction:column;gap:20px;">

        <!-- Host Resources -->
        <div class="hm-card">
          <div class="hm-card-header">
            <span class="hm-card-title">{{ t('healthMonitorView.cards.hostResources') }}</span>
            <div class="hm-cache-bar">
              <div class="hm-cache-dot" :class="resourceCache.loading ? 'loading' : (isResourceStale ? 'stale' : '')"></div>
              <span v-if="resourceCache.lastFetched">Last refreshed {{ formatRelativeTime(resourceCache.lastFetched) }}</span>
              <span v-else>{{ resourcesFailed ? 'Could not be read' : 'Not loaded' }}</span>
            </div>
          </div>
          <div class="hm-card-body">
            <ReadFailedNotice v-if="resourcesFailed && !resourcesKnown" dense data-testid="hm-resources-failed"
              text="The host resources could not be read just now." :retry="retryResources" />
            <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;">
              <div class="hm-resource-card">
                <div class="hm-resource-label">CPU</div>
                <div class="hm-resource-value" data-testid="hm-cpu" :style="{ color: resourcesKnown ? resourceColor(hostResources.cpu) : 'var(--hm-text-muted)' }">{{ resourcesKnown ? hostResources.cpu + '%' : '—' }}</div>
                <div class="hm-progress"><div class="hm-progress-fill" :class="progressColorFromPct(hostResources.cpu)" :style="{ width: hostResources.cpu + '%' }"></div></div>
                <div class="hm-resource-sub">{{ resourcesKnown ? hostResources.cpuCount + ' cores' : '—' }}</div>
              </div>
              <div class="hm-resource-card">
                <div class="hm-resource-label">Memory</div>
                <div class="hm-resource-value" :style="{ color: resourcesKnown ? resourceColor(hostResources.memoryPercent) : 'var(--hm-text-muted)' }">{{ resourcesKnown ? hostResources.memoryPercent + '%' : '—' }}</div>
                <div class="hm-progress"><div class="hm-progress-fill" :class="progressColorFromPct(hostResources.memoryPercent)" :style="{ width: hostResources.memoryPercent + '%' }"></div></div>
                <div class="hm-resource-sub">{{ resourcesKnown ? hostResources.memoryUsed + 'GB / ' + hostResources.memoryTotal + 'GB' : '—' }}</div>
              </div>
              <div class="hm-resource-card">
                <div class="hm-resource-label">Disk</div>
                <div class="hm-resource-value" :style="{ color: resourcesKnown ? resourceColor(hostResources.diskPercent) : 'var(--hm-text-muted)' }">{{ resourcesKnown ? hostResources.diskPercent + '%' : '—' }}</div>
                <div class="hm-progress"><div class="hm-progress-fill" :class="progressColorFromPct(hostResources.diskPercent)" :style="{ width: hostResources.diskPercent + '%' }"></div></div>
                <div class="hm-resource-sub">{{ resourcesKnown ? hostResources.diskUsed + 'GB / ' + hostResources.diskTotal + 'GB' : '—' }}</div>
              </div>
              <div class="hm-resource-card">
                <div class="hm-resource-label">Containers</div>
                <div class="hm-resource-value" style="color:var(--hm-cyan);">{{ dockerCache.lastFetched ? runningContainers + '/' + dockerCache.data.length : '—' }}</div>
                <div class="hm-progress"><div class="hm-progress-fill cyan" :style="{ width: dockerCache.data.length > 0 ? (runningContainers/dockerCache.data.length*100) + '%' : '0%' }"></div></div>
                <div class="hm-resource-sub">{{ dockerCache.lastFetched ? runningContainers + ' running' : '—' }}</div>
              </div>
            </div>
          </div>
        </div>

        <!-- Docker Containers -->
        <div class="hm-card">
          <div class="hm-card-header">
            <span class="hm-card-title">{{ t('healthMonitorView.cards.containers') }}</span>
            <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
              <div class="hm-cache-bar">
                <div class="hm-cache-dot" :class="dockerCache.loading ? 'loading' : (isDockerStale ? 'stale' : '')"></div>
                <span v-if="dockerCache.lastFetched">Cached {{ formatRelativeTime(dockerCache.lastFetched) }} · auto-refresh 3min</span>
                <span v-else>Loading takes 1–2 min via Docker API</span>
              </div>
              <button class="hm-btn hm-btn-ghost hm-btn-sm" @click="fetchDockerStats(true)" :disabled="dockerCache.loading">
                <span v-if="dockerCache.loading" style="animation:spin 1s linear infinite;display:inline-block;">⟳</span>
                <span v-else>⟳</span>
                {{ dockerCache.loading ? 'Loading...' : 'Refresh' }}
              </button>
            </div>
          </div>
          <div class="hm-card-body">
            <!-- Skeleton -->
            <div v-if="dockerCache.loading && dockerCache.data.length === 0"
              style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;">
              <div v-for="i in 20" :key="i" class="hm-skeleton-card">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                  <div style="flex:1;display:flex;flex-direction:column;gap:5px;">
                    <div class="hm-skeleton-line w-80"></div>
                    <div class="hm-skeleton-line w-40"></div>
                  </div>
                  <div class="hm-skeleton-line" style="width:10px;height:10px;border-radius:50%;"></div>
                </div>
                <div style="display:flex;flex-direction:column;gap:7px;margin-top:4px;">
                  <div class="hm-skeleton-line w-60"></div>
                  <div class="hm-skeleton-line h-3 full"></div>
                  <div class="hm-skeleton-line w-60"></div>
                  <div class="hm-skeleton-line h-3 full"></div>
                  <div class="hm-skeleton-line w-80"></div>
                </div>
              </div>
            </div>
            <!-- Real cards -->
            <div v-else-if="dockerCache.data.length > 0"
              style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;"
              :style="dockerCache.loading ? 'opacity:0.6;pointer-events:none;' : ''">
              <div v-for="c in dockerCache.data" :key="c.name"
                class="hm-docker-card"
                :class="c.status === 'running' ? 'running' : 'stopped'">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;">
                  <div style="overflow:hidden;">
                    <div class="hm-docker-name">{{ formatContainerName(c.name) }}</div>
                    <div class="hm-docker-id">{{ c.id }}</div>
                    <div class="hm-docker-ports">{{ c.ports }}</div>
                  </div>
                  <div style="width:9px;height:9px;border-radius:50%;flex-shrink:0;margin-top:3px;"
                    :style="{ background: c.status === 'running' ? 'var(--hm-green)' : 'var(--hm-red)', boxShadow: c.status === 'running' ? '0 0 5px rgba(0,229,160,0.5)' : '0 0 5px rgba(255,77,106,0.5)' }">
                  </div>
                </div>
                <div style="display:flex;flex-direction:column;gap:6px;">
                  <div>
                    <div style="display:flex;justify-content:space-between;">
                      <span class="hm-docker-stat-label">CPU</span>
                      <span class="hm-docker-stat-val" :class="cpuClass(c.cpu)">{{ c.cpu.toFixed(1) }}%</span>
                    </div>
                    <div class="hm-progress" style="margin-top:3px;"><div class="hm-progress-fill" :class="progressColorFromPct(c.cpu)" :style="{ width: Math.min(c.cpu, 100) + '%' }"></div></div>
                  </div>
                  <div>
                    <div style="display:flex;justify-content:space-between;">
                      <span class="hm-docker-stat-label">Memory</span>
                      <span class="hm-docker-stat-val" :class="cpuClass(c.memoryPercent)" style="font-size:10px;">{{ c.memoryUsage }}/{{ c.memoryLimit }}</span>
                    </div>
                    <div class="hm-progress" style="margin-top:3px;"><div class="hm-progress-fill" :class="progressColorFromPct(c.memoryPercent)" :style="{ width: Math.min(c.memoryPercent, 100) + '%' }"></div></div>
                  </div>
                  <div style="display:flex;justify-content:space-between;">
                    <span class="hm-docker-stat-label">Net ↓/↑</span>
                    <span class="hm-docker-stat-val dim" style="font-size:10px;">{{ c.networkRx }}/{{ c.networkTx }}</span>
                  </div>
                </div>
              </div>
            </div>
            <ReadFailedNotice v-else-if="dockerFailed" data-testid="hm-docker-failed"
              text="The containers could not be read just now." :retry="retryDocker" />
            <!-- Empty -->
            <div v-else class="hm-empty">
              <div class="hm-empty-icon"><Icon name="mdi:server" /></div>
              <div class="hm-empty-title">No container data</div>
              <div class="hm-empty-sub">Click Refresh to load (takes 1–2 min)</div>
            </div>
          </div>
        </div>

      </div>

      <!-- ══ ACTIVITY ════════════════════════════════════════════════════ -->
      <div v-if="activeTab === 'activity'" style="display:flex;flex-direction:column;gap:20px;">
        <div class="hm-card">
          <div class="hm-card-header">
            <span class="hm-card-title">{{ t('healthMonitorView.cards.eventStore') }}</span>
            <div style="display:flex;align-items:center;gap:10px;">
              <select aria-label="Filter activity" v-model="activityFilter" class="hm-select">
                <option value="all">All events</option>
                <option value="Agent">Agent</option>
                <option value="Token">Units</option>
                <option v-if="hmStakingOn" value="Locks">Locks</option>
                <option value="Governance">Governance</option>
                <option value="Dispute">Dispute</option>
                <option value="Federation">Federation</option>
              </select>
              <button class="hm-btn hm-btn-ghost hm-btn-sm" @click="fetchActivity">⟳ Refresh</button>
            </div>
          </div>
          <div class="hm-card-body" style="display:flex;flex-direction:column;gap:6px;max-height:600px;overflow-y:auto;">
            <div v-if="activityLoading" class="hm-empty">
              <div style="font-family:var(--hm-font-mono);font-size:11px;color:var(--hm-text-dim);">Loading events…</div>
            </div>
            <ReadFailedNotice v-else-if="activityFailed" data-testid="hm-activity-failed"
              text="The activity could not be read just now." :retry="fetchActivity" />
            <div v-else-if="filteredActivity.length === 0" class="hm-empty">
              <div class="hm-empty-icon"><Icon name="mdi:clipboard" /></div>
              <div class="hm-empty-title">No events</div>
              <div class="hm-empty-sub">EventStore activity will appear here after a health check.</div>
            </div>
            <div v-else>
              <div v-for="ev in filteredActivity" :key="ev.id" class="hm-activity-item">
                <div class="hm-activity-icon">{{ getEventIcon(ev.event_type) }}</div>
                <div style="flex:1;overflow:hidden;">
                  <div class="hm-activity-title" :title="ev.event_type">{{ ev.event_type ? ledgerEventLabel(ev.event_type) : ev.title }}</div>
                  <div class="hm-activity-msg">{{ ev.description || ev.agent_did || '—' }}</div>
                  <div class="hm-activity-meta">
                    <span>{{ formatRelativeTime(ev.timestamp) }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ══ PROMETHEUS ══════════════════════════════════════════════════ -->
      <div v-if="activeTab === 'prometheus'" style="display:flex;flex-direction:column;gap:20px;">

        <!-- Targets header summary -->
        <div class="hm-card">
          <div class="hm-card-header">
            <span class="hm-card-title">{{ t('healthMonitorView.cards.prometheus') }}</span>
            <div style="display:flex;align-items:center;gap:12px;">
              <div class="hm-cache-bar">
                <div class="hm-cache-dot" :class="promCache.loading ? 'loading' : ''"></div>
                <span v-if="promCache.lastFetched">{{ formatRelativeTime(promCache.lastFetched) }}</span>
              </div>
              <span v-if="promCache.data" style="font-family:var(--hm-font-mono);font-size:10px;">
                <span style="color:var(--hm-green);">{{ promCache.data.summary?.up_count ?? '—' }}</span>
                <span style="color:var(--hm-text-muted);"> / {{ promCache.data.summary?.total_targets ?? '—' }} UP</span>
              </span>
              <button class="hm-btn hm-btn-ghost hm-btn-sm" @click="() => fetchPrometheus()">⟳ Refresh</button>
            </div>
          </div>
          <div class="hm-card-body">
            <div v-if="promCache.loading && !promCache.data" class="hm-empty">
              <div style="font-family:var(--hm-font-mono);font-size:11px;color:var(--hm-text-dim);">Fetching targets…</div>
            </div>
            <ReadFailedNotice v-else-if="promFailed && !promCache.data" data-testid="hm-prom-failed"
              text="The Prometheus targets could not be read just now." :retry="retryPrometheus" />
            <div v-else-if="promCache.data && groupedTargets">
              <div v-for="(targets, tier) in groupedTargets" :key="tier" style="margin-bottom:16px;">
                <div class="hm-tier-header">{{ tier }}</div>
                <div style="display:flex;flex-wrap:wrap;gap:6px;">
                  <div v-for="target in targets" :key="target.instance" class="hm-target-pill" :class="target.health">
                    <div class="hm-target-dot" :class="target.health"></div>
                    <span class="hm-target-name">{{ target.instance_name || target.job }}</span>
                    <span class="hm-target-dur" v-if="target.scrape_ms">{{ target.scrape_ms }}ms</span>
                  </div>
                </div>
              </div>
            </div>
            <div v-else class="hm-empty">
              <div class="hm-empty-icon"><Icon name="mdi:radio-tower" /></div>
              <div class="hm-empty-title">No target data</div>
              <div class="hm-empty-sub">Click Refresh to load Prometheus targets.</div>
            </div>
          </div>
        </div>

        <!-- Active Alerts -->
        <div class="hm-card">
          <div class="hm-card-header">
            <span class="hm-card-title">Active Alerts</span>
            <div style="display:flex;gap:8px;">
              <!-- §FESUITE (V0578): "All Clear" is what an answered alerts read says; unread or failed is not clear -->
              <span v-if="!alertsAnswered" class="hm-badge hm-badge-inactive" data-testid="hm-alerts-unread">Not read</span>
              <span v-else-if="promAlerts.length === 0" class="hm-badge hm-badge-inactive">All Clear</span>
              <span v-else class="hm-badge hm-badge-firing">
                <div class="hm-badge-dot"></div>
                {{ firingAlertCount }} Firing
              </span>
            </div>
          </div>
          <div class="hm-card-body" style="display:flex;flex-direction:column;gap:8px;">
            <template v-if="!alertsAnswered">
              <!-- §ALERTS (2026-10-06): the alerts are vmalert's, read from the metrics store; a store this registry has
                   not been given, or a read it did not answer, is said as such and is not an all-clear -->
              <div v-if="promCache.data && promCache.data.alerts_configured === false" class="hm-empty-sub" data-testid="hm-alerts-not-configured">
                No metrics store is configured for this registry (VICTORIA_METRICS_URL), so its alerts cannot be shown.
              </div>
              <ReadFailedNotice v-else-if="promFailed || (promCache.data && promCache.data.alerts_readable === false)" dense data-testid="hm-alerts-failed"
                :text="'The alerts could not be read just now, so this is not an all-clear.' + (promCache.data?.alerts_reason ? ' (' + promCache.data.alerts_reason + ')' : '')" :retry="retryPrometheus" />
              <div v-else class="hm-empty-sub" data-testid="hm-alerts-reading">Reading the alerts…</div>
            </template>
            <div v-else-if="promAlerts.length === 0" class="hm-clear-banner" data-testid="hm-alerts-clear">
              ✓ No alerts firing (vmalert's rules, read from the metrics store)
            </div>
            <div v-else>
              <div v-for="alert in promAlerts" :key="alert.alertname + alert.instance" class="hm-alert-card" :class="alert.state">
                <div style="flex:1;">
                  <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
                    <div class="hm-alert-name">{{ alert.alertname }}</div>
                    <span class="hm-badge" :class="'hm-badge-' + (alert.state === 'firing' ? 'firing' : alert.state === 'pending' ? 'pending' : 'inactive')">
                      <div class="hm-badge-dot"></div>
                      {{ alert.state }}
                    </span>
                    <span class="hm-badge" :class="'hm-badge-' + (alert.severity === 'critical' ? 'critical' : alert.severity === 'warning' ? 'warn' : 'info')">
                      {{ alert.severity }}
                    </span>
                  </div>
                  <div class="hm-alert-instance">{{ alert.instance || alert.instance_name || alert.job }}</div>
                  <div v-if="alert.tier" style="font-family:var(--hm-font-mono);font-size:9px;color:var(--hm-text-muted);margin-top:2px;">tier: {{ alert.tier }}</div>
                  <div v-if="alert.annotations?.summary" style="font-size:11px;color:var(--hm-text-dim);margin-top:4px;">{{ alert.annotations.summary }}</div>
                  <div class="hm-alert-time" v-if="alert.active_at">Active since: {{ formatTimestamp(alert.active_at) }}</div>
                </div>
              </div>
            </div>
            <div v-if="alertsAnswered && promCache.data?.alerts_withheld?.sandbox" class="hm-empty-sub" data-testid="hm-alerts-withheld">
              {{ promCache.data.alerts_withheld.sandbox }} sandbox alert(s) not shown here.
            </div>
            <div v-if="alertsAnswered && promCache.data?.alerts_withheld?.inhibited" class="hm-empty-sub" data-testid="hm-alerts-inhibited">
              {{ promCache.data.alerts_withheld.inhibited }} warning(s) held back by a firing critical of the same family (the alert e-mails' rule).
            </div>
          </div>
        </div>

        <!-- Alert Rules (local) -->
        <div class="hm-card">
          <div class="hm-card-header">
            <span class="hm-card-title">Custom Alert Rules</span>
            <button v-if="isAdmin" class="hm-btn hm-btn-primary hm-btn-sm" @click="openRuleModal(null)">+ New Rule</button>
            <span v-else style="font-size:9px;color:var(--hm-text-muted);font-family:var(--hm-font-mono);">ADMIN ONLY</span>
          </div>
          <div class="hm-card-body">
            <div v-if="alertRules.length === 0" class="hm-empty">
              <div class="hm-empty-icon"><Icon name="mdi:scale-balance" /></div>
              <div class="hm-empty-title">No custom rules</div>
              <div class="hm-empty-sub">Rules evaluate locally against health check data.</div>
            </div>
            <div v-else style="overflow-x:auto;">
              <table class="hm-table" aria-label="Custom alert rules">
                <caption class="sr-only">Custom alert rules with metric, condition, and threshold.</caption>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Metric</th>
                    <th>Condition</th>
                    <th>Threshold</th>
                    <th>Severity</th>
                    <th>Enabled</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="rule in alertRules" :key="rule.id">
                    <td class="mono">{{ rule.name }}</td>
                    <td class="mono">{{ rule.metric }}</td>
                    <td class="mono">{{ rule.operator }}</td>
                    <td class="mono">{{ rule.threshold }}</td>
                    <td><span class="hm-badge" :class="'hm-badge-' + (rule.severity === 'critical' ? 'critical' : rule.severity === 'warning' ? 'warn' : 'info')">{{ rule.severity }}</span></td>
                    <td>
                      <label class="hm-toggle">
                        <input type="checkbox" v-model="rule.enabled" @change="saveAlertRules" :disabled="!isAdmin">
                        <span class="hm-toggle-slider" :style="!isAdmin ? 'opacity:0.3;cursor:not-allowed' : ''"></span>
                      </label>
                    </td>
                    <td style="display:flex;gap:6px;">
                      <button v-if="isAdmin" class="hm-btn hm-btn-ghost hm-btn-sm" @click="openRuleModal(rule)">Edit</button>
                      <button v-if="isAdmin" class="hm-btn hm-btn-danger hm-btn-sm" @click="deleteRule(rule.id)">Del</button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div style="margin-top:10px;font-family:var(--hm-font-mono);font-size:9px;color:var(--hm-text-muted);">
              Rules evaluated locally in-browser against health check data. Not backed by server.
            </div>
          </div>
        </div>

      </div>

      <!-- ══ PREDICTIONS ════════════════════════════════════════════════ -->
      <div v-if="activeTab === 'predictions'" style="display:flex;flex-direction:column;gap:20px;">
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:20px;">

          <!-- Performance Forecast -->
          <div class="hm-card">
            <div class="hm-card-header"><span class="hm-card-title">Performance Forecast</span></div>
            <div class="hm-card-body" style="display:flex;flex-direction:column;gap:10px;">
              <div style="display:flex;justify-content:space-between;font-size:12px;padding:5px 0;border-bottom:1px solid rgba(var(--nc-primary-rgb),0.06);">
                <span style="color:var(--hm-text-dim);">Next-hour load estimate</span>
                <span style="font-family:var(--hm-font-mono);" :style="{ color: !predictionsFromResources ? 'var(--hm-text-muted)' : predictions.nextHourLoad === 'high' ? 'var(--hm-yellow)' : 'var(--hm-green)' }" data-testid="hm-next-hour-load">{{ predictionsFromResources ? predictions.nextHourLoad : '—' }}</span>
              </div>
              <div style="display:flex;justify-content:space-between;font-size:12px;padding:5px 0;border-bottom:1px solid rgba(var(--nc-primary-rgb),0.06);">
                <span style="color:var(--hm-text-dim);">CPU forecast (±5% actual)</span>
                <span style="font-family:var(--hm-font-mono);color:var(--hm-text);">{{ predictionsFromResources ? predictions.cpuForecast + '%' : '—' }}</span>
              </div>
              <div style="display:flex;justify-content:space-between;font-size:12px;padding:5px 0;border-bottom:1px solid rgba(var(--nc-primary-rgb),0.06);">
                <span style="color:var(--hm-text-dim);">Memory forecast (±5% actual)</span>
                <span style="font-family:var(--hm-font-mono);color:var(--hm-text);">{{ predictionsFromResources ? predictions.memoryForecast + '%' : '—' }}</span>
              </div>
              <div style="display:flex;justify-content:space-between;font-size:12px;padding:5px 0;">
                <span style="color:var(--hm-text-dim);">Score trend (last 5 checks)</span>
                <span style="font-family:var(--hm-font-mono);" :style="{ color: healthHistory.length < 2 ? 'var(--hm-text-muted)' : predictions.scoreTrend >= 0 ? 'var(--hm-green)' : 'var(--hm-red)' }">{{ healthHistory.length < 2 ? '—' : (predictions.scoreTrend >= 0 ? '+' : '') + predictions.scoreTrend + '%' }}</span>
              </div>
              <div class="hm-chart-wrap">
                <canvas ref="forecastChart"></canvas>
              </div>
            </div>
          </div>

          <!-- Anomaly Detection -->
          <div class="hm-card">
            <div class="hm-card-header"><span class="hm-card-title">Anomaly Detection</span></div>
            <div class="hm-card-body">
              <!-- §FESUITE (V0578): "no anomalies" is said about a health check that answered, never about none -->
              <template v-if="!checkAnswered">
                <ReadFailedNotice v-if="checkFailed" dense data-testid="hm-anomalies-failed"
                  text="The health check could not be read, so nothing has been checked for anomalies." :retry="runHealthCheck" />
                <div v-else class="hm-empty-sub" data-testid="hm-anomalies-waiting">Waiting for the first health check.</div>
              </template>
              <div v-else-if="anomalies.length === 0" class="hm-clear-banner" style="font-size:11px;">✓ No anomalies detected in current dataset</div>
              <div v-else style="display:flex;flex-direction:column;gap:8px;">
                <div v-for="a in anomalies" :key="a.id" style="padding:10px 12px;border-radius:6px;border:1px solid var(--hm-border);background:var(--hm-surface-2);display:flex;gap:10px;">
                  <div style="width:3px;border-radius:2px;flex-shrink:0;" :style="{ background: a.severity === 'critical' ? 'var(--hm-red)' : 'var(--hm-yellow)' }"></div>
                  <div>
                    <div style="font-family:var(--hm-font-mono);font-size:11px;font-weight:600;color:var(--hm-text);">{{ a.title }}</div>
                    <div style="font-size:11px;color:var(--hm-text-dim);margin-top:2px;">{{ a.description }}</div>
                    <div style="font-family:var(--hm-font-mono);font-size:9px;color:var(--hm-text-muted);margin-top:4px;">{{ formatRelativeTime(a.detectedAt) }}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Capacity Planning -->
          <div class="hm-card">
            <div class="hm-card-header"><span class="hm-card-title">Capacity Planning</span></div>
            <div class="hm-card-body" style="display:flex;flex-direction:column;gap:14px;">
              <div>
                <div style="display:flex;justify-content:space-between;margin-bottom:5px;">
                  <span style="font-size:12px;color:var(--hm-text-dim);">Disk Storage</span>
                  <span style="font-family:var(--hm-font-mono);font-size:11px;color:var(--hm-text);">{{ resourcesKnown ? hostResources.diskUsed + 'GB / ' + hostResources.diskTotal + 'GB' : '—' }}</span>
                </div>
                <div class="hm-progress" style="height:6px;"><div class="hm-progress-fill" :class="progressColorFromPct(hostResources.diskPercent)" :style="{ width: hostResources.diskPercent + '%' }"></div></div>
                <div style="font-family:var(--hm-font-mono);font-size:9px;color:var(--hm-text-muted);margin-top:4px;">{{ resourcesKnown ? hostResources.diskPercent + '% used — ' + (hostResources.diskTotal - hostResources.diskUsed) + 'GB free' : '—' }}</div>
              </div>
              <div>
                <div style="display:flex;justify-content:space-between;margin-bottom:5px;">
                  <span style="font-size:12px;color:var(--hm-text-dim);">Memory</span>
                  <span style="font-family:var(--hm-font-mono);font-size:11px;color:var(--hm-text);">{{ resourcesKnown ? hostResources.memoryUsed + 'GB / ' + hostResources.memoryTotal + 'GB' : '—' }}</span>
                </div>
                <div class="hm-progress" style="height:6px;"><div class="hm-progress-fill" :class="progressColorFromPct(hostResources.memoryPercent)" :style="{ width: hostResources.memoryPercent + '%' }"></div></div>
                <div style="font-family:var(--hm-font-mono);font-size:9px;color:var(--hm-text-muted);margin-top:4px;">{{ resourcesKnown ? hostResources.memoryPercent + '% used' : '—' }}</div>
              </div>
              <div style="padding:8px 10px;border-radius:6px;background:var(--hm-surface-2);border:1px solid var(--hm-border);">
                <div style="font-family:var(--hm-font-mono);font-size:9px;letter-spacing:0.08em;text-transform:uppercase;color:var(--hm-text-muted);margin-bottom:6px;">Insights</div>
                <div v-for="ins in trendInsights" :key="ins.id" style="font-size:11px;color:var(--hm-text-dim);padding:2px 0;">{{ ins.message }}</div>
              </div>
            </div>
          </div>

        </div>
      </div>

    </div><!-- /hm-content -->

    <!-- ── Alert Rule Modal ────────────────────────────────────────────── -->
    <Teleport to="body">
      <div v-if="showRuleModal" class="hm-modal-backdrop" @click.self="showRuleModal = false">
        <div class="hm-modal">
          <div class="hm-modal-header">
            <span class="hm-modal-title">{{ editingRule ? 'Edit Alert Rule' : 'New Alert Rule' }}</span>
            <button class="hm-btn hm-btn-ghost hm-btn-sm" @click="showRuleModal = false">✕</button>
          </div>
          <div class="hm-modal-body">
            <div>
              <label class="hm-form-label">Rule Name</label>
              <input class="hm-input" v-model="ruleForm.name" placeholder="e.g. High Response Time">
            </div>
            <div>
              <label for="healthmonitorultimate-sel-673" class="hm-form-label">Metric</label>
              <select id="healthmonitorultimate-sel-673" class="hm-form-select" v-model="ruleForm.metric">
                <option value="response_time">Response Time (ms)</option>
                <option value="error_rate">Error Rate (%)</option>
                <option value="health_score">Health Score (%)</option>
                <option value="cpu_usage">CPU Usage (%)</option>
                <option value="memory_usage">Memory Usage (%)</option>
              </select>
            </div>
            <div>
              <label for="healthmonitorultimate-sel-683" class="hm-form-label">Condition</label>
              <select id="healthmonitorultimate-sel-683" class="hm-form-select" v-model="ruleForm.operator">
                <option value="greater_than">Greater Than</option>
                <option value="less_than">Less Than</option>
              </select>
            </div>
            <div>
              <label class="hm-form-label">Threshold</label>
              <input class="hm-input" type="number" v-model.number="ruleForm.threshold">
            </div>
            <div>
              <label for="healthmonitorultimate-sel-694" class="hm-form-label">Severity</label>
              <select id="healthmonitorultimate-sel-694" class="hm-form-select" v-model="ruleForm.severity">
                <option value="info">Info</option>
                <option value="warning">Warning</option>
                <option value="critical">Critical</option>
              </select>
            </div>
          </div>
          <div class="hm-modal-footer">
            <button class="hm-btn hm-btn-ghost" @click="showRuleModal = false">Cancel</button>
            <button class="hm-btn hm-btn-primary" @click="saveRule">Save Rule</button>
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
import { ref, reactive, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { ledgerEventLabel } from '@/services/ledgerEventLabel'
const LOCK_EVENTS = new Set(['TokensStaked', 'TokensUnstaked', 'RewardsDistributed', 'RewardDistributed', 'RewardsAutoCompounded'])
import { useRoute } from 'vue-router'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
dayjs.extend(relativeTime)
import { useAuthStore } from '@/stores/auth'
import { useRealtimeStore } from '@/stores/realtime'
import { useUIStore } from '@/stores/ui'
import { apiClient } from '@/services/api/client'
import { Chart, registerables } from 'chart.js'
import { useI18n } from '@/composables/useI18n'
import '@/components/healthMonitor/tp-healthmonitor.css'
import { liveOld } from '@/services/ledgerNames'

Chart.register(...registerables)

const { t } = useI18n()

const authStore   = useAuthStore()
const uiStore     = useUIStore()

// ── Auth checks ───────────────────────────────────────────────────────────
const hasAgentAuth = computed(() => !!authStore.agentToken)
const isAdmin = computed(() => authStore.isAdmin)

// ── Tabs ──────────────────────────────────────────────────────────────────
// §ALERTS (2026-10-06): the header strip's alert chip opens /health-monitor?tab=prometheus. The tab is read at the first
// arrival AND on a query-only change while the page is already open (vue-router reuses the component then).
const route = useRoute()
const TAB_IDS = ['overview', 'timeline', 'infrastructure', 'activity', 'prometheus', 'predictions']
function tabFromQuery(): string | null {
  const q = route?.query?.tab        // no router (a unit mount): no tab asked
  const v = Array.isArray(q) ? q[0] : q
  return typeof v === 'string' && TAB_IDS.includes(v) ? v : null
}
const activeTab = ref(tabFromQuery() || 'overview')
watch(() => route?.query?.tab, () => { const v = tabFromQuery(); if (v) activeTab.value = v })
const tabs = [
  { id: 'overview',        label: 'Overview' },
  { id: 'timeline',        label: 'Timeline' },
  { id: 'infrastructure',  label: 'Infrastructure' },
  { id: 'activity',        label: 'Activity' },
  { id: 'prometheus',      label: 'Prometheus' },
  { id: 'predictions',     label: 'Predictions' },
]

// ── Health state ──────────────────────────────────────────────────────────
const loading            = ref(false)
const overallHealth      = ref(0)
const healthyServices    = ref(0)
const totalServices      = ref(0)
const avgResponseTime    = ref(0)
// §FESUITE (V0578): no "last check" time before a check answered (it said the page's own load time)
const lastCheckTime      = ref<Date | null>(null)
const serviceGroups      = reactive<Record<string, any>>({})
// §FESUITE (V0578): every read on this page keeps its own state, so a figure says "—" until its read answered and a
// failed read says it failed. Before this the score read a red "0%" before the first check, a failed network read drew a
// green "0.00%" error rate, a failed Prometheus read drew "All Clear", a failed resources read "0%" CPU, memory and disk,
// a failed activity or docker read "No events" / "No container data", and the Predictions tab "No anomalies detected"
// with no check answered at all.
const checkAnswered   = ref(false)   // a health check has answered since the page opened
const checkFailed     = ref(false)   // the latest health check failed
const networkRead     = ref<'unread' | 'ok' | 'failed'>('unread')
const netOk           = computed(() => networkRead.value === 'ok')
const resourcesFailed = ref(false)
const dockerFailed    = ref(false)
const activityFailed  = ref(false)
const promFailed      = ref(false)
// the forecast's CPU, memory and load were computed from host resources that had answered (not from their zeros)
const predictionsFromResources = ref(false)

// Endpoint breakdown counts
const devEndpointsTotal    = ref(0)
const devEndpointsHealthy  = ref(0)
const agentEndpointsTotal  = ref(0)
const agentEndpointsHealthy= ref(0)
const agentEndpointsNA     = ref(0)   // agent-tier checks skipped (no active agent) — N/A, not failures
const pubEndpointsTotal    = ref(0)
const pubEndpointsHealthy  = ref(0)

// Auto-refresh
const autoRefresh    = ref(true)
const refreshInterval= ref(30000)
const nextRefreshIn  = ref(30)
let refreshTimer: any = null
let countdownTimer: any = null

// ── Network metrics ───────────────────────────────────────────────────────
const networkMetrics = reactive({ totalAgents: 0, activeAgents: 0, p50: 0, p95: 0, errorRate: 0 })

// ── Docker cache (TTL 3min) ───────────────────────────────────────────────
const DOCKER_TTL   = 3 * 60 * 1000
const RESOURCE_TTL = 90 * 1000
const PROM_TTL     = 30 * 1000

const dockerCache   = reactive<{ data: any[], lastFetched: Date|null, loading: boolean }>({ data: [], lastFetched: null, loading: false })
const resourceCache = reactive<{ data: any, lastFetched: Date|null, loading: boolean }>({ data: null, lastFetched: null, loading: false })
const promCache     = reactive<{ data: any, lastFetched: Date|null, loading: boolean }>({ data: null, lastFetched: null, loading: false })

const hostResources = reactive({ cpu: 0, cpuCount: 0, memoryPercent: 0, memoryUsed: 0, memoryTotal: 0, diskPercent: 0, diskUsed: 0, diskTotal: 0 })

const isDockerStale   = computed(() => dockerCache.lastFetched   ? (Date.now() - dockerCache.lastFetched.getTime())   > DOCKER_TTL   : false)
const isResourceStale = computed(() => resourceCache.lastFetched ? (Date.now() - resourceCache.lastFetched.getTime()) > RESOURCE_TTL : false)
const resourcesKnown  = computed(() => !!resourceCache.lastFetched)
const runningContainers = computed(() => dockerCache.data.filter((c: any) => c.status === 'running').length)

// ── Activity ──────────────────────────────────────────────────────────────
const activityFeed    = ref<any[]>([])
const activityFilter  = ref('all')
// the lock events' filter where a lock can be opened (registry-config's staking_enabled), in §VOCAB's words
const { config: hmRegistryCfg } = useRegistryConfig()
const hmStakingOn = computed(() => hmRegistryCfg.value.staking_enabled === true)
const activityLoading = ref(false)

const filteredActivity = computed(() => {
  if (activityFilter.value === 'all') return activityFeed.value
  // the lock events by name (their types share no prefix of their own); every other filter by its type's prefix
  if (activityFilter.value === 'Locks') return activityFeed.value.filter(e => LOCK_EVENTS.has(liveOld(e.event_type)))
  return activityFeed.value.filter(e => e.event_type?.startsWith(activityFilter.value) || e.title?.startsWith(activityFilter.value))
})

// ── Prometheus ────────────────────────────────────────────────────────────
const groupedTargets = computed(() => {
  if (!promCache.data?.targets) return null
  const groups: Record<string, any[]> = {}
  for (const t of promCache.data.targets) {
    const tier = t.tier || 'other'
    const key = tier.charAt(0).toUpperCase() + tier.slice(1)
    if (!groups[key]) groups[key] = []
    groups[key].push(t)
  }
  return groups
})

const promAlerts     = computed<any[]>(() => promCache.data?.alerts ?? [])
/** §ALERTS: true only when the alerts themselves were read (the page's call can answer while the store did not) */
const alertsAnswered = computed(() => !!promCache.data && promCache.data.alerts_readable !== false
  && promCache.data.alerts_configured !== false)
const firingAlertCount = computed(() => promAlerts.value.filter((a: any) => a.state === 'firing').length)

// ── Alert rules ───────────────────────────────────────────────────────────
const alertRules   = ref<any[]>([])
const showRuleModal= ref(false)
const editingRule  = ref(false)
const ruleForm     = reactive({ id: '', name: '', metric: 'response_time', operator: 'greater_than', threshold: 1000, severity: 'warning' })

// ── History ───────────────────────────────────────────────────────────────
const healthHistory    = ref<any[]>([])
const selectedTimeRange= ref('24h')
const timeRanges = [
  { v: '1h', l: '1h' }, { v: '6h', l: '6h' }, { v: '24h', l: '24h' }, { v: '7d', l: '7d' }
]

const filteredHistory = computed(() => {
  const now = Date.now()
  const cutoff: Record<string, number> = { '1h': 3600000, '6h': 21600000, '24h': 86400000, '7d': 604800000 }
  const ms = cutoff[selectedTimeRange.value] ?? 86400000
  return healthHistory.value.filter(h => (now - new Date(h.timestamp.endsWith('Z') || h.timestamp.includes('+') ? h.timestamp : h.timestamp + 'Z').getTime()) < ms)
})

// ── Predictions ───────────────────────────────────────────────────────────
const predictions = reactive({ nextHourLoad: 'normal', cpuForecast: 0, memoryForecast: 0, scoreTrend: 0 })
const anomalies   = ref<any[]>([])
const trendInsights = ref<any[]>([])

// ── Charts ────────────────────────────────────────────────────────────────
const healthChart   = ref<HTMLCanvasElement|null>(null)
const responseChart = ref<HTMLCanvasElement|null>(null)
const forecastChart = ref<HTMLCanvasElement|null>(null)
const charts: Record<string, Chart> = {}

function destroyChart(key: string) {
  if (charts[key]) { try { charts[key].destroy() } catch { /* expected */ } delete charts[key] }
}

// ── Score helpers ─────────────────────────────────────────────────────────
const scoreColor = computed(() => {
  const h = overallHealth.value
  if (h >= 95) return '#00e5a0'
  if (h >= 80) return 'var(--nc-primary)'
  if (h >= 60) return '#f5c842'
  return '#ff4d6a'
})

const scoreColorClass = computed(() => {
  const h = overallHealth.value
  if (h >= 95) return 'green'
  if (h >= 80) return ''
  if (h >= 60) return 'warn'
  return 'red'
})

function getHealthStatus(score: number) {
  if (score >= 95) return 'Excellent'
  if (score >= 80) return 'Good'
  if (score >= 60) return 'Fair'
  if (score >= 40) return 'Degraded'
  return 'Critical'
}

function getScoreClass(score: number) {
  if (score >= 95) return 'excellent'
  if (score >= 80) return 'good'
  if (score >= 60) return 'fair'
  return 'critical'
}

function getProgressColor(score: number) {
  if (score >= 95) return 'green'
  if (score >= 80) return 'cyan'
  if (score >= 60) return 'yellow'
  return 'red'
}

function progressColorFromPct(pct: number) {
  if (pct < 50) return 'green'
  if (pct < 75) return 'yellow'
  if (pct < 90) return 'yellow'
  return 'red'
}

function resourceColor(pct: number) {
  if (pct < 50) return 'var(--hm-green)'
  if (pct < 75) return 'var(--hm-cyan)'
  if (pct < 90) return 'var(--hm-yellow)'
  return 'var(--hm-red)'
}

function cpuClass(pct: number) {
  if (pct < 50) return 'ok'
  if (pct < 80) return 'warn'
  return 'crit'
}

// ── Group helpers ─────────────────────────────────────────────────────────
function formatGroupName(name: string) {
  const m: Record<string, string> = { auth: 'Authentication', teg: 'Payments', staking: 'Locks', governance: 'Governance', agents: 'Agents', federation: 'Federation', metrics: 'Metrics' }
  return m[name] || name
}

function getGroupIcon(name: string) {
  const m: Record<string, string> = { auth: '🔐', teg: '💰', staking: '💎', governance: '⚖️', agents: '🤖', federation: '🌐', metrics: '📊' }
  return m[name] || '📦'
}

function getEventIcon(type: string) {
  if (type?.includes('Agent')) return '🤖'
  if (type?.includes('Token') || type?.includes('Transfer')) return '💸'
  if (type?.includes('Stake') || type?.includes('Reward')) return '💎'
  if (type?.includes('Proposal') || type?.includes('Vote') || type?.includes('Governance')) return '⚖️'
  if (type?.includes('Dispute')) return '⚖️'
  if (type?.includes('Federation')) return '🌐'
  if (type?.includes('Attestation')) return '🔏'
  return '⚙️'
}

function formatContainerName(name: string) {
  return name.replace(/^agentvault[_-]/, '').replace(/_/g, ' ').replace(/-/g, ' ').split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
}

// ── Time helpers ──────────────────────────────────────────────────────────
function formatTime(d: Date | string | null) {
  if (!d) return '—'
  const dt = typeof d === 'string' ? new Date(d.endsWith('Z') || d.includes('+') ? d : d + 'Z') : d
  return dt.toLocaleTimeString(appLocale())
}

function formatTimestamp(d: string) {
  const utc = d.endsWith('Z') || d.includes('+') ? d : d + 'Z'
  return new Date(utc).toLocaleString(appLocale())
}

function formatRelativeTime(d: Date | string){
  if (!d) return '—'
  return dayjs(d).fromNow()
}

// ── Health Check ──────────────────────────────────────────────────────────
async function runHealthCheck() {
  loading.value = true
  try {
    // Real system health from the combined infra+resource endpoint. Public +
    // developer tiers reflect true service health; agent-tier endpoints that 401/403
    // without an active agent are treated as N/A (skipped) — NOT counted as failures —
    // so the headline reads true even when no agent is signed in. (Was POST
    // /health-check/composite, which dragged the score down to "unhealthy" whenever
    // agent endpoints 401'd with no agent present.)
    const res = await apiClient.get('/admin/combined-health', {
      params: {
        include_auth_tests: true,
        ...(authStore.agentToken ? { agent_token: authStore.agentToken } : {}),
      },
    })
    const data = (res.data && res.data.health) ? res.data.health : res.data
    // an answer that carries no results measured nothing: it is a failed check, never a score
    if (!data || !data.results) throw new Error('the health check answered without results')

    Object.keys(serviceGroups).forEach(k => delete serviceGroups[k])

    // An agent-tier endpoint is N/A (not a failure) when there is no active agent,
    // or when it returned 401/403 (auth-gated, expected without an agent token).
    const isAgentNA = (ep: any) =>
      ep.authRequired === 'agent' && (!hasAgentAuth.value || ep.statusCode === 401 || ep.statusCode === 403)

    if (data && data.results) {
      let healthy = 0, total = 0
      let devH = 0, devT = 0, agentH = 0, agentT = 0, agentNA = 0, pubH = 0, pubT = 0
      for (const [, eps] of Object.entries(data.results)) {
        for (const ep of eps as any[]) {
          if (isAgentNA(ep)) { agentNA++; continue }           // excluded from the score
          total++
          if (ep.authRequired === 'developer') { devT++; if (ep.healthy) { devH++; healthy++ } }
          else if (ep.authRequired === 'agent') { agentT++; if (ep.healthy) { agentH++; healthy++ } }
          else { pubT++; if (ep.healthy) { pubH++; healthy++ } }
        }
      }
      overallHealth.value      = total > 0 ? Math.round((healthy / total) * 100) : 100
      healthyServices.value    = healthy
      totalServices.value      = total
      devEndpointsTotal.value  = devT; devEndpointsHealthy.value  = devH
      agentEndpointsTotal.value= agentT; agentEndpointsHealthy.value= agentH
      agentEndpointsNA.value   = agentNA
      pubEndpointsTotal.value  = pubT; pubEndpointsHealthy.value  = pubH

      for (const [name, eps] of Object.entries(data.results) as [string, any[]][]) {
        // per-group health likewise excludes agent-N/A so a no-agent session reads true
        let gh = 0, gt = 0
        for (const ep of eps) { if (isAgentNA(ep)) continue; gt++; if (ep.healthy) gh++ }
        serviceGroups[name] = {
          label: formatGroupName(name), icon: getGroupIcon(name),
          health: gt > 0 ? Math.round((gh / gt) * 100) : 100,
          endpoints: eps.slice(0, 4)
        }
      }
    }

    let totalTime = 0, cnt = 0
    for (const eps of Object.values(data.results || {}) as any[][]) {
      for (const ep of eps) { if (ep.responseTime) { totalTime += ep.responseTime; cnt++ } }
    }
    avgResponseTime.value = cnt > 0 ? Math.round(totalTime / cnt) : 0
    lastCheckTime.value = new Date()
    checkAnswered.value = true
    checkFailed.value = false

    storeHealthSnapshot()
    updatePredictions()
    evaluateLocalAlerts()

  } catch (e: any) {
    console.error('Health check failed:', e)
    checkFailed.value = true
    uiStore.showError?.('Health check failed: ' + (e?.message || e))
  } finally {
    loading.value = false
  }

  // Side loads
  fetchNetworkMetrics()
  if (activeTab.value === 'activity') fetchActivity()
}

async function fetchNetworkMetrics() {
  try {
    const res = await apiClient.get('/metrics/network-health')
    const d = res.data
    networkMetrics.totalAgents  = d.total_agents  || 0
    networkMetrics.activeAgents = d.active_agents || 0
    networkMetrics.p50          = d.response_time_p50 || 0
    networkMetrics.p95          = d.response_time_p95 || 0
    networkMetrics.errorRate    = d.error_rate || 0
    networkRead.value = 'ok'
  } catch {
    networkRead.value = 'failed'
  }
}

// ── Docker ────────────────────────────────────────────────────────────────
async function fetchDockerStats(force = false) {
  if (!force && dockerCache.lastFetched && !isDockerStale.value) return
  dockerCache.loading = true
  try {
    const res = await apiClient.get('/admin/docker-stats')
    const d = res.data
    const containers = []
    for (const [name, stats] of Object.entries(d.containers || {}) as [string, any][]) {
      const n = name.toLowerCase()
      let ports = 'internal'
      if (n.includes('registry_a') && !n.includes('db'))         ports = '8000'
      else if (n.includes('registry_b') && !n.includes('db'))    ports = '8001'
      else if (n.includes('teg_layer_a'))                        ports = '8100'
      else if (n.includes('teg_layer_b'))                        ports = '8101'
      else if (n.includes('event_store') && !n.includes('db'))   ports = '8200'
      else if (n.includes('registry_db_a'))                      ports = '5433'
      else if (n.includes('registry_db_b'))                      ports = '5434'
      else if (n.includes('event_store_db'))                     ports = '5435'
      else if (n.includes('teg_db_a'))                           ports = '5436'
      else if (n.includes('teg_db_b'))                           ports = '5437'
      else if (n.includes('prometheus'))                         ports = '9090'
      else if (n.includes('grafana'))                            ports = '3000'
      else if (n.includes('node_exporter') || n.includes('node-exporter')) ports = '9100'
      else if (n.includes('opa'))                                ports = '8288'
      else if (n.includes('spire'))                              ports = 'mTLS'
      else if (n.includes('nginx'))                              ports = 'sidecar'

      containers.push({
        name, id: stats.id?.substring(0, 8) || '', status: stats.status,
        cpu: stats.cpu?.percentage || 0,
        memoryUsage: `${Math.round(stats.memory?.usage_mb || 0)}MB`,
        memoryLimit: `${Math.round(stats.memory?.limit_mb || 0)}MB`,
        memoryPercent: stats.memory?.percentage || 0,
        networkRx: `${Math.round(stats.network?.rx_mb || 0)}MB`,
        networkTx: `${Math.round(stats.network?.tx_mb || 0)}MB`,
        ports
      })
    }
    dockerCache.data = containers
    dockerCache.lastFetched = new Date()

    if (d.host) {
      hostResources.cpu           = Math.round(d.host.cpu_percent || 0)
      hostResources.cpuCount      = d.host.cpu_count || 0
      hostResources.memoryPercent = Math.round(d.host.memory?.percent || 0)
      hostResources.memoryUsed    = Math.round((d.host.memory?.used || 0) / 1073741824)
      hostResources.memoryTotal   = Math.round((d.host.memory?.total || 0) / 1073741824)
      hostResources.diskPercent   = Math.round(d.host.disk?.percent || 0)
      hostResources.diskUsed      = Math.round((d.host.disk?.used || 0) / 1073741824)
      hostResources.diskTotal     = Math.round((d.host.disk?.total || 0) / 1073741824)
      resourceCache.lastFetched   = new Date()
      resourcesAnswered()
    }
    dockerFailed.value = false
  } catch (e) {
    console.error('Docker stats failed:', e)
    dockerFailed.value = true
  } finally {
    dockerCache.loading = false
  }
}

// ── System Resources (lightweight, for header tiles) ─────────────────────
async function fetchSystemResources(force = false) {
  if (!force && resourceCache.lastFetched && !isResourceStale.value) return
  resourceCache.loading = true
  try {
    const res = await apiClient.get('/admin/system-resources')
    const d = res.data
    hostResources.cpu           = Math.round(d.cpu?.percent || 0)
    hostResources.cpuCount      = d.cpu?.count || 0
    hostResources.memoryPercent = Math.round(d.memory?.percent || 0)
    hostResources.memoryUsed    = Math.round(d.memory?.used_gb || 0)
    hostResources.memoryTotal   = Math.round(d.memory?.total_gb || 0)
    hostResources.diskPercent   = Math.round(d.disk?.percent || 0)
    hostResources.diskUsed      = Math.round(d.disk?.used_gb || 0)
    hostResources.diskTotal     = Math.round(d.disk?.total_gb || 0)
    resourceCache.lastFetched   = new Date()
    resourcesAnswered()
  } catch {
    resourcesFailed.value = true
  }
  finally { resourceCache.loading = false }
}

// the resources answered: their failure (if any) is over, and a forecast made before they arrived is made again from them
function resourcesAnswered() {
  resourcesFailed.value = false
  if (checkAnswered.value && !predictionsFromResources.value) updatePredictions()
}
function retryResources() { return fetchSystemResources(true) }
function retryDocker() { return fetchDockerStats(true) }
function retryPrometheus() { return fetchPrometheus(true) }

// ── Activity ──────────────────────────────────────────────────────────────
async function fetchActivity() {
  activityLoading.value = true
  try {
    const res = await apiClient.get('/admin/system-activity', { params: { limit: 80 } })
    activityFeed.value = Array.isArray(res.data?.events) ? res.data.events : []
    activityFailed.value = false
  } catch (e) {
    console.error('Activity fetch failed:', e)
    activityFeed.value = []
    activityFailed.value = true
  } finally {
    activityLoading.value = false
  }
}

// ── Prometheus ────────────────────────────────────────────────────────────
async function fetchPrometheus(force = false) {
  if (!force && promCache.lastFetched && (Date.now() - promCache.lastFetched.getTime()) < PROM_TTL) return
  promCache.loading = true
  try {
    const res = await apiClient.get('/admin/prometheus-metrics')
    promCache.data = res.data
    promCache.lastFetched = new Date()
    promFailed.value = false
  } catch (e) {
    console.error('Prometheus fetch failed:', e)
    // an earlier answer is not this one: the alerts it held (or its all-clear) are not shown as current
    promCache.data = null
    promCache.lastFetched = null
    promFailed.value = true
  } finally {
    promCache.loading = false
  }
}

// ── History ───────────────────────────────────────────────────────────────
function storeHealthSnapshot() {
  const snap = {
    timestamp: new Date().toISOString(),
    score: overallHealth.value,
    healthyServices: healthyServices.value,
    totalServices: totalServices.value,
    avgResponseTime: avgResponseTime.value,
    errorCount: totalServices.value - healthyServices.value
  }
  healthHistory.value.unshift(snap)
  if (healthHistory.value.length > 100) healthHistory.value = healthHistory.value.slice(0, 100)
  try { localStorage.setItem('hm_history_v2', JSON.stringify(healthHistory.value.slice(0, 50))) } catch { /* expected */ }
  updateTimelineCharts()
}

function loadHistory() {
  try {
    const s = localStorage.getItem('hm_history_v2')
    if (s) healthHistory.value = JSON.parse(s)
  } catch { /* expected */ }
}

// ── Predictions ───────────────────────────────────────────────────────────
function updatePredictions() {
  predictionsFromResources.value = resourcesKnown.value
  predictions.cpuForecast    = Math.round(hostResources.cpu * (1 + (Math.random() - 0.5) * 0.1))
  predictions.memoryForecast = Math.round(hostResources.memoryPercent * (1 + (Math.random() - 0.5) * 0.1))
  predictions.nextHourLoad   = hostResources.cpu > 70 ? 'high' : 'normal'

  const recent = healthHistory.value.slice(0, 5)
  if (recent.length >= 2) {
    predictions.scoreTrend = Math.round(recent[0].score - recent[recent.length - 1].score)
  }

  const insights: any[] = []
  if (overallHealth.value >= 95) insights.push({ id: 1, message: '✓ System performing optimally' })
  else if (overallHealth.value < 80) insights.push({ id: 1, message: `⚠ Health score below threshold: ${overallHealth.value}%` })
  if (avgResponseTime.value < 300) insights.push({ id: 2, message: `✓ Fast response times: ${avgResponseTime.value}ms avg` })
  else if (avgResponseTime.value > 1000) insights.push({ id: 2, message: `⚠ Slow responses: ${avgResponseTime.value}ms avg` })
  if (hostResources.diskPercent > 80) insights.push({ id: 3, message: `⚠ Disk at ${hostResources.diskPercent}% — consider cleanup` })
  trendInsights.value = insights.slice(0, 4)

  const newAnomalies: any[] = []
  for (const [name, group] of Object.entries(serviceGroups) as [string, any][]) {
    if (group.health < 80) {
      newAnomalies.push({ id: name, severity: group.health < 50 ? 'critical' : 'warning', title: `${group.label} degraded`, description: `Health: ${group.health}%`, detectedAt: new Date().toISOString() })
    }
  }
  anomalies.value = newAnomalies

  updateForecastChart()
}

// ── Local alert evaluation ────────────────────────────────────────────────
function evaluateLocalAlerts() {
  for (const rule of alertRules.value) {
    if (!rule.enabled) continue
    let val = 0
    if (rule.metric === 'health_score')  val = overallHealth.value
    if (rule.metric === 'response_time') val = avgResponseTime.value
    if (rule.metric === 'cpu_usage')     val = hostResources.cpu
    if (rule.metric === 'memory_usage')  val = hostResources.memoryPercent
    const triggered = rule.operator === 'greater_than' ? val > rule.threshold : val < rule.threshold
    if (triggered) import.meta.env.DEV && console.log(`[Alert] Rule "${rule.name}" triggered: ${val} ${rule.operator} ${rule.threshold}`)
  }
}

// ── Alert rules CRUD ──────────────────────────────────────────────────────
function openRuleModal(rule: any) {
  if (rule) {
    Object.assign(ruleForm, rule)
    editingRule.value = true
  } else {
    Object.assign(ruleForm, { id: '', name: '', metric: 'response_time', operator: 'greater_than', threshold: 1000, severity: 'warning' })
    editingRule.value = false
  }
  showRuleModal.value = true
}

function saveRule() {
  if (!ruleForm.name) return
  if (editingRule.value) {
    const idx = alertRules.value.findIndex(r => r.id === ruleForm.id)
    if (idx >= 0) alertRules.value[idx] = { ...ruleForm }
  } else {
    alertRules.value.push({ ...ruleForm, id: Date.now().toString(), enabled: true })
  }
  saveAlertRules()
  showRuleModal.value = false
}

function deleteRule(id: string) {
  alertRules.value = alertRules.value.filter(r => r.id !== id)
  saveAlertRules()
}

function saveAlertRules() {
  try { localStorage.setItem('hm_rules_v2', JSON.stringify(alertRules.value)) } catch { /* expected */ }
}

function loadAlertRules() {
  try {
    const s = localStorage.getItem('hm_rules_v2')
    if (s) alertRules.value = JSON.parse(s)
    else {
      // Default seed rules
      alertRules.value = [
        { id: '1', name: 'High Response Time', metric: 'response_time', operator: 'greater_than', threshold: 2000, severity: 'warning', enabled: true },
        { id: '2', name: 'Low Health Score',   metric: 'health_score',   operator: 'less_than',    threshold: 80,   severity: 'critical', enabled: true },
        { id: '3', name: 'High CPU Usage',      metric: 'cpu_usage',      operator: 'greater_than', threshold: 85,   severity: 'warning', enabled: false },
      ]
    }
  } catch { /* expected */ }
}

// ── Charts ────────────────────────────────────────────────────────────────
const CHART_OPTS = {
  responsive: true, maintainAspectRatio: false,
  plugins: { legend: { display: false } },
  scales: {
    y: { beginAtZero: true, grid: { color: 'rgba(var(--nc-primary-rgb),0.06)' }, ticks: { color: '#6b8aaa', font: { family: 'IBM Plex Mono', size: 10 } } },
    x: { grid: { color: 'rgba(var(--nc-primary-rgb),0.04)' }, ticks: { color: '#6b8aaa', font: { family: 'IBM Plex Mono', size: 9 }, maxTicksLimit: 8 } }
  }
}

function updateTimelineCharts() {
  if (activeTab.value !== 'timeline') return
  nextTick(() => initTimelineCharts())
}

function initTimelineCharts() {
  const hist = filteredHistory.value.slice(0, 30).reverse()
  const labels = hist.map(h => new Date(h.timestamp.endsWith('Z') || h.timestamp.includes('+') ? h.timestamp : h.timestamp + 'Z').toLocaleTimeString(appLocale(), { hour: '2-digit', minute: '2-digit' }))

  destroyChart('health')
  if (healthChart.value) {
    charts['health'] = new Chart(healthChart.value, {
      type: 'line',
      data: {
        labels,
        datasets: [{ label: 'Health %', data: hist.map(h => h.score), borderColor: 'var(--nc-primary)', backgroundColor: 'rgba(var(--nc-primary-rgb),0.08)', tension: 0.4, pointRadius: 3, pointBackgroundColor: 'var(--nc-primary)' }]
      },
      options: { ...CHART_OPTS, scales: { ...CHART_OPTS.scales, y: { ...CHART_OPTS.scales.y, max: 100 } } } as any
    })
  }

  destroyChart('response')
  if (responseChart.value) {
    charts['response'] = new Chart(responseChart.value, {
      type: 'bar',
      data: {
        labels,
        datasets: [{ label: 'Avg Response (ms)', data: hist.map(h => h.avgResponseTime), backgroundColor: 'rgba(77,159,255,0.5)', borderColor: '#4d9fff', borderWidth: 1 }]
      },
      options: CHART_OPTS as any
    })
  }
}

function updateForecastChart() {
  if (activeTab.value !== 'predictions') return
  nextTick(() => {
    const hist = healthHistory.value.slice(0, 6).reverse()
    const histLabels = hist.map(h => new Date(h.timestamp).toLocaleTimeString(appLocale(), { hour: '2-digit', minute: '2-digit' }))
    const forecastLabels = ['+15m', '+30m', '+45m', '+1h', '+90m', '+2h']
    const lastScore = hist[hist.length - 1]?.score ?? overallHealth.value
    const forecastData = forecastLabels.map((_, i) => Math.max(0, Math.min(100, lastScore + (Math.random() - 0.4) * 3 * (i + 1))))

    destroyChart('forecast')
    if (forecastChart.value) {
      charts['forecast'] = new Chart(forecastChart.value, {
        type: 'line',
        data: {
          labels: [...histLabels, ...forecastLabels],
          datasets: [
            { label: 'Actual', data: [...hist.map(h => h.score), ...Array(6).fill(null)], borderColor: 'var(--nc-primary)', backgroundColor: 'rgba(var(--nc-primary-rgb),0.08)', tension: 0.4, pointRadius: 3, pointBackgroundColor: 'var(--nc-primary)' },
            { label: 'Forecast', data: [...Array(histLabels.length).fill(null), lastScore, ...forecastData], borderColor: '#b46cff', backgroundColor: 'rgba(180,108,255,0.06)', borderDash: [5, 4], tension: 0.4, pointRadius: 3, pointBackgroundColor: '#b46cff' }
          ]
        },
        options: { ...CHART_OPTS, plugins: { legend: { display: true, labels: { color: '#6b8aaa', font: { family: 'IBM Plex Mono', size: 10 } } } }, scales: { ...CHART_OPTS.scales, y: { ...CHART_OPTS.scales.y, max: 100 } } } as any
      })
    }
  })
}

// ── Export ────────────────────────────────────────────────────────────────
function exportReport() {
  const report = {
    timestamp: new Date().toISOString(),
    overall: { health: overallHealth.value, healthyServices: healthyServices.value, totalServices: totalServices.value, avgResponseTime: avgResponseTime.value },
    services: serviceGroups,
    network: networkMetrics,
    resources: hostResources,
    history: healthHistory.value.slice(0, 50),
    prometheus: promCache.data?.summary,
    alerts: { firing: firingAlertCount.value, rules: alertRules.value }
  }
  const b = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' })
  const u = URL.createObjectURL(b)
  const a = document.createElement('a')
  a.href = u; a.download = `health-report-${Date.now()}.json`; a.click()
  URL.revokeObjectURL(u)
}

// ── Auto-refresh ──────────────────────────────────────────────────────────
function toggleAutoRefresh() {
  autoRefresh.value ? startAutoRefresh() : stopAutoRefresh()
}

function startAutoRefresh() {
  stopAutoRefresh()
  // HM1 (audit 2026-05-07): skip the polling tick + countdown decrement when
  // the browser tab is hidden — saves ~12 health-check round-trips per hour
  // per backgrounded admin window. The countdown keeps its current value so
  // when the tab becomes visible again the user sees a stale-but-honest "Xs
  // ago" instead of a desynced counter.
  refreshTimer = setInterval(() => {
    if (document.visibilityState !== 'hidden') runHealthCheck()
  }, refreshInterval.value)
  nextRefreshIn.value = Math.floor(refreshInterval.value / 1000)
  countdownTimer = setInterval(() => {
    if (document.visibilityState === 'hidden') return
    nextRefreshIn.value--
    if (nextRefreshIn.value <= 0) nextRefreshIn.value = Math.floor(refreshInterval.value / 1000)
  }, 1000)
}

function stopAutoRefresh() {
  clearInterval(refreshTimer); clearInterval(countdownTimer)
  refreshTimer = null; countdownTimer = null
}

function updateRefreshInterval() {
  if (autoRefresh.value) startAutoRefresh()
}

// ── Tab change watchers ───────────────────────────────────────────────────
watch(selectedTimeRange, () => {
  if (activeTab.value === 'timeline') nextTick(() => initTimelineCharts())
})

watch(activeTab, (tab) => {
  if (tab === 'timeline')       nextTick(() => initTimelineCharts())
  if (tab === 'predictions')    updateForecastChart()
  if (tab === 'infrastructure') { fetchSystemResources(); fetchDockerStats() }
  if (tab === 'activity')       fetchActivity()
  if (tab === 'prometheus')     fetchPrometheus()
})

// ── Lifecycle ─────────────────────────────────────────────────────────────
onMounted(() => {
  loadHistory()
  loadAlertRules()
  runHealthCheck()
  fetchSystemResources(true)
  fetchPrometheus(true)
  if (autoRefresh.value) startAutoRefresh()
})

onUnmounted(() => {
  stopAutoRefresh()
  Object.keys(charts).forEach(k => destroyChart(k))
})
</script>

<style scoped>
@keyframes spin { to { transform: rotate(360deg); } }

/* ── Agent Auth Warning Banner ── */
.hm-agent-auth-banner {
  padding: 0;
  border-radius: 8px;
  border: 1px solid rgba(255, 180, 50, 0.25);
  background: linear-gradient(135deg, rgba(255, 180, 50, 0.06) 0%, rgba(255, 120, 30, 0.04) 100%);
  overflow: hidden;
}
.hm-agent-auth-banner-inner {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  padding: 18px 20px;
}
.hm-agent-auth-icon {
  flex-shrink: 0;
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: rgba(255, 180, 50, 0.1);
  border: 1px solid rgba(255, 180, 50, 0.2);
  color: rgba(255, 180, 50, 0.7);
}
.hm-agent-auth-text {
  flex: 1;
  min-width: 0;
}
.hm-agent-auth-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: rgba(255, 180, 50, 0.85);
  margin-bottom: 6px;
}
.hm-agent-auth-desc {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem;
  line-height: 1.6;
  letter-spacing: 0.02em;
  color: rgba(255, 180, 50, 0.5);
}
</style>
