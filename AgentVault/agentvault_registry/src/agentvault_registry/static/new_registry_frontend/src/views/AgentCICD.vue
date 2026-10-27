<template>
  <!-- §pass50.1 — inline background removed so DashboardLayout's <ViewAmbient>
       paints the default tone through. Was solid var(--cicd-bg) blocking it. -->
  <div class="cicd-module" style="min-height:100vh;padding:24px;position:relative;z-index:1;">

    <!-- Page Header -->
    <div style="margin-bottom:20px;display:flex;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;gap:10px;">
      <div>
        <div class="cicd-section-title" data-tour="cicd-agent-hero" style="margin-bottom:4px;">{{ t('agentCicdView.title') }}</div>
        <div style="font-size:18px;font-weight:700;color:var(--cicd-text);">{{ agentName }}</div>
        <div style="font-family:var(--cicd-font-mono);font-size:11px;color:var(--cicd-text-muted);margin-top:2px;">{{ agentDid }}</div>
      </div>
      <div style="display:flex;gap:8px;align-items:center;">
        <button
          v-if="!notOwner"
          class="cicd-btn cicd-btn-primary"
          @click="showDeploy = true"
          data-tour="cicd-deploy"
        >▶ {{ t('agentCicdView.deploy') }}</button>
      </div>
    </div>

    <!-- §FESUITE — the webhook secret is answered once, at creation: shown here until the person says it is saved -->
    <div v-if="cicdStore.revealedWebhookSecret" class="cicd-card cicd-secret" role="region" data-testid="cicd-webhook-secret"
         :aria-label="t('agentCicdView.secret.aria', 'Webhook secret')">
      <div class="cicd-section-title">{{ tp('agentCicdView.secret.title', 'Webhook secret for {name}', { name: cicdStore.revealedWebhookSecret.pipeline }) }}</div>
      <p class="cicd-secret-note">{{ t('agentCicdView.secret.note', 'Shown once. Your CI server signs its webhook calls with it: store it there now.') }}</p>
      <code class="cicd-secret-code">{{ cicdStore.revealedWebhookSecret.secret }}</code>
      <div class="cicd-secret-actions">
        <button type="button" class="cicd-btn cicd-btn-ghost cicd-btn-sm" @click="copySecret">{{ secretCopied ? t('agentCicdView.secret.copied', 'Copied') : t('agentCicdView.secret.copy', 'Copy') }}</button>
        <button type="button" class="cicd-btn cicd-btn-primary cicd-btn-sm" data-testid="cicd-secret-saved" @click="cicdStore.dismissWebhookSecret()">{{ t('agentCicdView.secret.saved', 'I saved it') }}</button>
      </div>
    </div>

    <!-- §FESUITE (worker C's owner_scoping_cicd_door): another developer's agent showed zero counts and a Deploy button
         over refused reads; it says whose agent it is and asks nothing the server refuses -->
    <div v-if="notOwner" class="cicd-card" role="status" data-testid="cicd-not-owner" style="margin-bottom:20px;">
      {{ t('agentCicdView.notOwner', "This agent belongs to another developer. Its pipelines, versions and deployments are visible only to its owner.") }}
    </div>
    <template v-if="!notOwner">
    <!-- Stats Row -->
    <div class="cicd-stat-grid" style="margin-bottom:20px;">
      <div class="cicd-stat-tile">
        <div class="stat-label">{{ t('agentCicdView.stats.pipelines') }}</div>
        <!-- §FESUITE (V0577): a count of a list that could not be read is "—", never 0 -->
        <div class="stat-value" data-testid="cicd-stat-pipelines">{{ cicdStore.readFailed.pipelines ? '—' : cicdStore.pipelines.length }}</div>
      </div>
      <div class="cicd-stat-tile">
        <div class="stat-label">{{ t('agentCicdView.stats.versions') }}</div>
        <div class="stat-value" data-testid="cicd-stat-versions">{{ cicdStore.readFailed.versions ? '—' : cicdStore.versions.length }}</div>
        <div class="stat-sub" v-if="cicdStore.activeVersion">{{ t('agentCicdView.stats.activeVersion', { v: cicdStore.activeVersion.version }) }}</div>
      </div>
      <div class="cicd-stat-tile">
        <div class="stat-label">{{ t('agentCicdView.stats.deployments') }}</div>
        <div class="stat-value" data-testid="cicd-stat-deployments">{{ cicdStore.readFailed.deployments ? '—' : cicdStore.deploymentStats.total }}</div>
        <div v-if="!cicdStore.readFailed.deployments" class="stat-sub">{{ t('agentCicdView.stats.succeeded', { n: cicdStore.deploymentStats.successful }) }}</div>
      </div>
      <div class="cicd-stat-tile">
        <div class="stat-label">{{ t('agentCicdView.stats.successRate') }}</div>
        <!-- §FESUITE (V0577): no rate without deployments to rate. An unread list, and an agent never deployed, read a red
             "0.0%": never-observed is not zero percent -->
        <div v-if="cicdStore.readFailed.deployments || !cicdStore.deploymentStats.total" class="stat-value" data-testid="cicd-stat-rate">—</div>
        <div v-else class="stat-value" data-testid="cicd-stat-rate" :style="{color: +cicdStore.deploymentStats.successRate >= 80 ? 'var(--cicd-green)' : 'var(--cicd-red)'}">
          {{ cicdStore.deploymentStats.successRate }}%
        </div>
        <div v-if="!cicdStore.readFailed.deployments" class="stat-sub">{{ t('agentCicdView.stats.failed', { n: cicdStore.deploymentStats.failed }) }}</div>
      </div>
    </div>

    <!-- §pass49 F2 — Health & Identity stat row (drift / keys / flags / mTLS) -->
    <div class="cicd-stat-grid" style="margin-bottom:14px;">
      <div class="cicd-stat-tile" :class="{ 'tile-warn-c5': hasOpenFlag('persistent_drift') }">
        <div class="stat-label">{{ t('agentCicdView.health.driftStatus') }}</div>
        <div class="stat-value" style="font-size:14px;">
          <span v-if="hasOpenFlag('persistent_drift')" style="color:#ff7676;"><Icon name="mdi:alert" /> {{ t('agentCicdView.health.flagged') }}</span>
          <span v-else-if="driftLastPulledAt" style="color:var(--cicd-green, #5dffae);">✓ {{ t('agentCicdView.health.ok') }}</span>
          <span v-else style="color:var(--cicd-text-muted);">—</span>
        </div>
        <div class="stat-sub" v-if="driftLastPulledAt">{{ t('agentCicdView.health.lastPulled', { ago: fromNow(driftLastPulledAt) }) }}</div>
      </div>
      <div class="cicd-stat-tile">
        <div class="stat-label">{{ t('agentCicdView.health.signingKey') }}</div>
        <div class="stat-value" style="font-size:14px;font-family:var(--cicd-font-mono);">
          <span v-if="signingKeys.length">#{{ signingKeys[0].rotation_seq }}</span>
          <span v-else style="color:var(--cicd-text-muted);">—</span>
        </div>
        <div class="stat-sub" v-if="signingKeys[0]?.created_at">{{ t('agentCicdView.health.rotated', { ago: fromNow(signingKeys[0].created_at) }) }}</div>
      </div>
      <div class="cicd-stat-tile" :class="{ 'tile-warn-c5': hasOpenFlag('jws_verify_threshold') }">
        <div class="stat-label">{{ t('agentCicdView.health.jwsVerify') }}</div>
        <div class="stat-value" style="font-size:14px;">
          <span v-if="!flagsReadable" style="color:var(--cicd-text-muted);" :title="t('agentCicdView.health.adminOnly', 'Only an administrator can read this agent\'s flags')">—</span>
          <span v-else-if="hasOpenFlag('jws_verify_threshold')" style="color:#ff7676;"><Icon name="mdi:alert" /> {{ t('agentCicdView.health.failures') }}</span>
          <span v-else style="color:var(--cicd-green, #5dffae);">✓ {{ t('agentCicdView.health.ok') }}</span>
        </div>
      </div>
      <div class="cicd-stat-tile" :class="{ 'tile-warn-c5': openFlags.length > 0 }">
        <div class="stat-label">{{ t('agentCicdView.health.activeFlags') }}</div>
        <div class="stat-value" style="font-size:14px;">
          <span v-if="!flagsReadable" style="color:var(--cicd-text-muted);" :title="t('agentCicdView.health.adminOnly', 'Only an administrator can read this agent\'s flags')">—</span>
          <span v-else :style="{ color: openFlags.length ? '#ffb245' : 'var(--cicd-green, #5dffae)' }">{{ openFlags.length }}</span>
        </div>
        <div class="stat-sub" v-if="openFlags.length">{{ openFlags.length }} {{ t('agentCicdView.health.pendingAck') }}</div>
      </div>
    </div>

    <!-- §pass49 F2 — Cross-pollination panel: drift / signing keys / flags -->
    <div class="cicd-c5-panel" v-if="showC5">
      <div class="cicd-c5-section">
        <div class="cicd-c5-section-header">
          <span>{{ t('agentCicdView.c5.drift.title') }}</span>
          <button class="cicd-btn cicd-btn-ghost cicd-btn-sm" @click="forceDriftRefresh">{{ t('agentCicdView.c5.drift.refreshBtn') }}</button>
        </div>
        <div v-if="driftRefreshMsg" style="font-size:11px;color:var(--cicd-text-muted);">{{ driftRefreshMsg }}</div>
        <div v-if="driftEvents.length">
          <div v-for="ev in driftEvents.slice(0, 5)" :key="ev.id" style="padding:6px 0;border-bottom:1px solid rgba(96,128,192,0.08);font-size:11px;font-family:var(--cicd-font-mono);">
            <div>{{ fromNow(ev.timestamp) }} · <span style="color:#ffb245">{{ (ev.data?.drifted_fields || []).slice(0,5).join(', ') }}</span></div>
          </div>
        </div>
        <div v-else style="font-size:11px;color:var(--cicd-text-muted);padding:8px 0;">{{ t('agentCicdView.c5.drift.none') }}</div>
      </div>

      <div class="cicd-c5-section">
        <div class="cicd-c5-section-header">
          <span>{{ t('agentCicdView.c5.keys.title') }}</span>
          <button v-if="isAdmin" class="cicd-btn cicd-btn-primary cicd-btn-sm" @click="rotateKey">{{ t('agentCicdView.c5.keys.rotateBtn') }}</button>
        </div>
        <div v-if="signingKeys.length">
          <div v-for="k in signingKeys.slice(0, 5)" :key="k.rotation_seq" style="padding:6px 0;border-bottom:1px solid rgba(96,128,192,0.08);font-size:11px;font-family:var(--cicd-font-mono);">
            <span>#{{ k.rotation_seq }}</span> ·
            <span>{{ t('agentCicdView.c5.keys.created') }}: {{ fmtDate(k.created_at) }}</span>
            <span v-if="k.expires_at"> · <span style="color:#ffb245">{{ t('agentCicdView.c5.keys.expires') }}: {{ fmtDate(k.expires_at) }}</span></span>
          </div>
        </div>
        <div v-else style="font-size:11px;color:var(--cicd-text-muted);padding:8px 0;">{{ t('agentCicdView.c5.keys.none') }}</div>
        <div v-if="rotateMsg" style="margin-top:6px;font-size:11px;color:var(--cicd-green);">{{ rotateMsg }}</div>
      </div>

      <div class="cicd-c5-section">
        <div class="cicd-c5-section-header">
          <span>{{ t('agentCicdView.c5.flags.title') }}</span>
        </div>
        <div v-if="flagsForAgent.length">
          <div v-for="f in flagsForAgent" :key="f.id" style="padding:8px 0;border-bottom:1px solid rgba(96,128,192,0.08);">
            <div style="display:flex;justify-content:space-between;align-items:center;font-size:11px;">
              <div>
                <span class="cicd-badge cicd-badge-active" style="background:rgba(255,178,69,0.18);color:#ffb245;">{{ f.flag_type }}</span>
                <span style="margin-left:8px;color:var(--cicd-text-muted);">{{ f.reason || '—' }}</span>
              </div>
              <div style="display:flex;gap:6px;align-items:center;">
                <span v-if="f.acknowledged_at" style="color:var(--cicd-green);">✓ ack {{ fromNow(f.acknowledged_at) }}</span>
                <span v-else style="color:#f0c64f;"><Icon name="mdi:timer-sand" /> {{ fromNow(f.raised_at) }}</span>
                <button v-if="isAdmin && !f.acknowledged_at" class="cicd-btn cicd-btn-success cicd-btn-sm" @click="ackFlag(f)">{{ t('agentCicdView.c5.flags.ack') }}</button>
              </div>
            </div>
          </div>
        </div>
        <div v-else style="font-size:11px;color:var(--cicd-green);padding:8px 0;">{{ t('agentCicdView.c5.flags.none') }}</div>
      </div>
    </div>

    <div style="margin-bottom:14px;">
      <button class="cicd-btn cicd-btn-ghost cicd-btn-sm" @click="showC5 = !showC5">
        {{ showC5 ? '▾' : '▸' }} {{ t('agentCicdView.c5.toggleLabel') }}
      </button>
    </div>

    <!-- Tab Bar -->
    <div class="cicd-tabs" role="tablist" :aria-label="t('agentCicdView.title')" style="margin-bottom:20px;">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        type="button"
        role="tab"
        class="cicd-tab"
        :data-tour="'cicd-tab-' + tab.id"
        :data-tab="tab.id"
        :class="{ active: activeTab === tab.id }"
        :aria-selected="activeTab === tab.id"
        @click="activeTab = tab.id"
      >
        {{ tab.icon }} {{ tab.label }}
        <span v-if="tab.count" style="
          margin-left:5px;
          background:var(--cicd-surface-3);
          border-radius:10px;
          padding:1px 6px;
          font-size:9px;
          color:var(--cicd-text-muted);
        ">{{ tab.count }}</span>
      </button>
    </div>

    <!-- Tab: Builder -->
    <div v-if="activeTab === 'builder'">
      <PipelineBuilder :agent-did="agentDid" />
    </div>

    <!-- Tab: Pipelines -->
    <div v-else-if="activeTab === 'pipelines'">
      <div style="display:flex;justify-content:flex-end;margin-bottom:12px;">
        <button class="cicd-btn cicd-btn-primary" @click="activeTab = 'builder'">+ New Pipeline</button>
      </div>

      <div v-if="cicdStore.loadingStates.pipelines" class="cicd-empty">
        <div style="font-size:22px;animation:cicd-pulse 1s infinite;">◌</div>
      </div>
      <ReadFailedNotice v-else-if="cicdStore.readFailed.pipelines" :retry="() => cicdStore.fetchPipelines(agentDid)"
        data-testid="cicd-pipelines-failed" />
      <div v-else-if="!cicdStore.pipelines.length" class="cicd-empty">
        <div class="cicd-empty-icon">⬡</div>
        <div class="cicd-empty-title">No pipelines configured</div>
        <div class="cicd-empty-sub">Create your first pipeline using the Pipeline Builder tab.</div>
        <button class="cicd-btn cicd-btn-primary" style="margin-top:10px;" @click="activeTab = 'builder'">Open Builder</button>
      </div>
      <div v-else style="display:flex;flex-direction:column;gap:10px;">
        <div
          v-for="p in cicdStore.pipelines"
          :key="p.id"
          class="cicd-card cicd-card-accent"
          data-testid="cicd-pipeline"
          :data-pipeline-id="p.id"
          style="padding:14px 16px;"
        >
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;">
            <div style="flex:1;min-width:0;">
              <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
                <span style="font-family:var(--cicd-font-mono);font-size:13px;font-weight:700;color:var(--cicd-text);">{{ p.pipeline_name }}</span>
                <span class="cicd-badge" :class="p.is_active ? 'cicd-badge-active' : 'cicd-badge-inactive'">
                  {{ p.is_active ? 'active' : 'inactive' }}
                </span>
                <span class="cicd-badge cicd-badge-manual" style="font-size:9px;">{{ p.trigger_type }}</span>
              </div>
              <div style="display:flex;gap:16px;font-size:11px;color:var(--cicd-text-muted);font-family:var(--cicd-font-mono);">
                <span>{{ p.pipeline_config.stages?.length ?? 0 }} stages</span>
                <span v-if="p.last_run_at">Last run: {{ fmtDate(p.last_run_at) }}</span>
                <span v-if="p.webhook_url">webhook configured</span>
              </div>
            </div>
            <div style="display:flex;gap:6px;">
              <button
                type="button"
                class="cicd-btn cicd-btn-success cicd-btn-sm"
                :disabled="!p.webhook_url"
                @click="runPipeline(p.id)"
                :title="p.webhook_url ? t('agentCicdView.pipelines.trigger', 'Trigger') : 'No webhook: add one to the pipeline to run it'"
                :aria-label="tp('agentCicdView.pipelines.triggerAria', 'Trigger {name}', { name: p.pipeline_name })"
              ><span aria-hidden="true">▶</span></button>
              <button
                type="button"
                class="cicd-btn cicd-btn-ghost cicd-btn-sm"
                data-action="edit"
                @click="editPipeline(p)"
                :title="t('agentCicdView.pipelines.edit', 'Edit')"
                :aria-label="tp('agentCicdView.pipelines.editAria', 'Edit {name}', { name: p.pipeline_name })"
              ><span aria-hidden="true">✎</span></button>
              <button
                type="button"
                class="cicd-btn cicd-btn-danger cicd-btn-sm"
                data-action="delete"
                @click="askConfirm('delete', p)"
                :title="t('agentCicdView.pipelines.delete', 'Delete')"
                :aria-label="tp('agentCicdView.pipelines.deleteAria', 'Delete {name}', { name: p.pipeline_name })"
              ><span aria-hidden="true">✕</span></button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Tab: Versions -->
    <div v-else-if="activeTab === 'versions'">
      <div style="display:flex;justify-content:flex-end;margin-bottom:12px;">
        <button class="cicd-btn cicd-btn-primary" @click="showCreateVersion = true">+ Create Version</button>
      </div>

      <div v-if="cicdStore.loadingStates.versions" class="cicd-empty">
        <div style="font-size:22px;animation:cicd-pulse 1s infinite;">◌</div>
      </div>
      <ReadFailedNotice v-else-if="cicdStore.readFailed.versions" :retry="() => cicdStore.fetchVersions(agentDid)"
        data-testid="cicd-versions-failed" />
      <div v-else-if="!cicdStore.versions.length" class="cicd-empty">
        <div class="cicd-empty-icon">◈</div>
        <div class="cicd-empty-title">No versions yet</div>
        <div class="cicd-empty-sub">Tag a version to track your agent's release history.</div>
      </div>
      <div v-else style="display:flex;flex-direction:column;gap:10px;">
        <div
          v-for="v in cicdStore.versions"
          :key="v.id"
          class="cicd-card"
          data-testid="cicd-version"
          :data-version="v.version"
          :style="v.is_active ? 'border-color:rgba(0,229,160,0.3);' : ''"
          style="padding:14px 16px;"
        >
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;">
            <div style="flex:1;min-width:0;">
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:5px;">
                <span style="font-family:var(--cicd-font-mono);font-size:14px;font-weight:700;color:var(--cicd-cyan);">v{{ v.version }}</span>
                <span v-if="v.is_active" class="cicd-badge cicd-badge-success">★ active</span>
                <span v-if="v.is_stable" class="cicd-badge cicd-badge-running" style="font-size:9px;">stable</span>
              </div>
              <div v-if="v.release_notes || v.changelog" style="font-size:12px;color:var(--cicd-text-muted);margin-bottom:4px;">
                {{ v.release_notes || v.changelog }}
              </div>
              <div style="font-family:var(--cicd-font-mono);font-size:10px;color:var(--cicd-text-muted);display:flex;gap:14px;">
                <span>{{ fmtDate(v.created_at) }}</span>
                <span v-if="v.deployment_count != null">{{ v.deployment_count }} deployments</span>
              </div>
            </div>
            <div style="display:flex;gap:6px;">
              <button
                v-if="!v.is_active"
                type="button"
                class="cicd-btn cicd-btn-success cicd-btn-sm"
                data-action="activate"
                @click="cicdStore.activateVersion(agentDid, v.id)"
              >{{ t('agentCicdView.versions.activate', 'Activate') }}</button>
              <button
                type="button"
                class="cicd-btn cicd-btn-ghost cicd-btn-sm"
                data-action="rollback"
                @click="askConfirm('rollback', v)"
              >{{ t('agentCicdView.versions.rollback', 'Rollback') }}</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Tab: Deployments -->
    <div v-else-if="activeTab === 'deployments'">
      <!-- §FESUITE — the relay status is ASKED for (it dials the agent's own endpoint; an agent with no relay answered 503
           every 15 s on every visit, polled from mount whatever the tab). Once it answers, it refreshes while this tab is open. -->
      <div v-if="!relayStatus" class="cicd-relay-ask">
        <button type="button" class="cicd-btn cicd-btn-ghost cicd-btn-sm" :disabled="relayLoading" data-testid="cicd-relay-check" @click="checkRelay">
          {{ relayLoading ? t('agentCicdView.relay.checking', 'Checking…') : t('agentCicdView.relay.check', 'Check relay status') }}
        </button>
        <span v-if="relayOutcome && relayOutcome.kind !== 'failed'" class="cicd-relay-none"
          :data-testid="`cicd-relay-${relayOutcome.kind}`" :data-relay-outcome="relayOutcome.kind">{{ relayOutcome.text }}</span>
      </div>
      <ReadFailedNotice v-if="!relayStatus && relayOutcome?.kind === 'failed'" dense :text="relayOutcome.text" :retry="checkRelay"
        data-testid="cicd-relay-failed" />
      <div v-if="relayStatus" class="relay-card" :class="{'relay-healthy': relayStatus.healthy, 'relay-down': !relayStatus.healthy}">
        <div class="relay-header">
          <div class="relay-title-row">
            <span class="relay-dot" :class="relayStatus.container_status === 'running' ? 'relay-dot-up' : relayStatus.container_status === 'exited' ? 'relay-dot-down' : 'relay-dot-warn'"></span>
            <span class="relay-title">RELAY STATUS</span>
            <span class="relay-version">v{{ relayStatus.relay_version || '?' }}</span>
          </div>
        </div>
        <div class="relay-grid">
          <div class="relay-stat">
            <span class="relay-stat-label">Container</span>
            <span class="relay-stat-val" :class="relayStatus.container_status === 'running' ? 'relay-val-up' : 'relay-val-down'">{{ relayStatus.container_status }}</span>
          </div>
          <div class="relay-stat">
            <span class="relay-stat-label">Health</span>
            <span class="relay-stat-val" :class="relayStatus.healthy ? 'relay-val-up' : 'relay-val-down'">{{ relayStatus.healthy ? 'healthy' : 'unhealthy' }}</span>
          </div>
          <div class="relay-stat">
            <span class="relay-stat-label">Uptime</span>
            <span class="relay-stat-val">{{ formatUptime(relayStatus.uptime_seconds) }}</span>
          </div>
          <div class="relay-stat">
            <span class="relay-stat-label">Restarts</span>
            <span class="relay-stat-val">{{ relayStatus.restart_count || 0 }}</span>
          </div>
          <div class="relay-stat">
            <span class="relay-stat-label">Pending Webhooks</span>
            <span class="relay-stat-val" :class="relayStatus.pending_webhooks > 0 ? 'relay-val-warn' : ''">{{ relayStatus.pending_webhooks || 0 }}</span>
          </div>
          <div class="relay-stat" v-if="relayStatus.last_restart">
            <span class="relay-stat-label">Last Restart</span>
            <span class="relay-stat-val">{{ new Date(relayStatus.last_restart).toLocaleTimeString(appLocale()) }}</span>
          </div>
        </div>
        <div class="relay-actions">
          <button class="cicd-btn cicd-btn-sm" :class="relayStatus.container_status === 'running' ? 'relay-btn-restart' : 'relay-btn-start'"
            @click="relayAction(relayStatus.container_status === 'running' ? 'relay_restart' : 'relay_start')"
            :disabled="relayLoading">
            {{ relayStatus.container_status === 'running' ? '↻ Restart' : '▶ Start' }}
          </button>
          <button v-if="relayStatus.container_status === 'running'" class="cicd-btn cicd-btn-sm relay-btn-stop"
            @click="relayAction('relay_stop')" :disabled="relayLoading">
            ■ Stop
          </button>
          <span v-if="relayLoading" class="relay-loading">Processing...</span>
          <span v-if="relayMessage" class="relay-message" data-testid="cicd-relay-message">{{ relayMessage }}</span>
          <span v-if="relayRefreshFailed" class="relay-message" data-testid="cicd-relay-refresh-failed">{{ relayRefreshFailed }}</span>
        </div>
      </div>

      <!-- Filters -->
      <div style="display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap;">
        <select v-model="cicdStore.filters.environment" class="cicd-input" style="width:160px;cursor:pointer;" :aria-label="t('agentCicdView.filters.environment', 'Environment')">
          <option value="">All Environments</option>
          <option value="dev">dev</option>
          <option value="staging">staging</option>
          <option value="production">production</option>
        </select>
        <select v-model="cicdStore.filters.status" class="cicd-input" style="width:140px;cursor:pointer;" :aria-label="t('agentCicdView.filters.status', 'Status')">
          <option value="">All Status</option>
          <option value="pending">pending</option>
          <option value="running">running</option>
          <option value="success">success</option>
          <option value="failed">failed</option>
          <option value="cancelled">cancelled</option>
        </select>
        <button
          class="cicd-btn cicd-btn-ghost cicd-btn-sm"
          @click="cicdStore.clearFilters()"
          v-if="cicdStore.filters.environment || cicdStore.filters.status"
        >✕ Clear</button>
      </div>

      <div v-if="cicdStore.loadingStates.deployments" class="cicd-empty">
        <div style="font-size:22px;animation:cicd-pulse 1s infinite;">◌</div>
      </div>
      <ReadFailedNotice v-else-if="cicdStore.readFailed.deployments" :retry="() => cicdStore.fetchDeployments(agentDid)"
        data-testid="cicd-deployments-failed" />
      <div v-else-if="!cicdStore.filteredDeployments.length" class="cicd-empty">
        <div class="cicd-empty-icon">▶</div>
        <div class="cicd-empty-title">No deployments found</div>
      </div>

      <!-- Deployment table -->
      <div v-else class="cicd-card" style="overflow:hidden;">
        <table class="cicd-table">
          <thead>
            <tr>
              <th>Status</th>
              <th>Environment</th>
              <th>Type</th>
              <th>Version</th>
              <th>Started</th>
              <th>Duration</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="d in cicdStore.filteredDeployments"
              :key="d.id"
            >
              <td>
                <span class="cicd-badge" :class="`cicd-badge-${d.status}`">
                  <span class="cicd-badge-dot"></span>
                  {{ d.status }}
                </span>
              </td>
              <td>
                <span style="font-family:var(--cicd-font-mono);font-size:11px;color:var(--cicd-cyan);">{{ d.environment }}</span>
              </td>
              <td>
                <span style="font-family:var(--cicd-font-mono);font-size:10px;color:var(--cicd-text-muted);">{{ d.deployment_type || 'pipeline' }}</span>
              </td>
              <td class="mono">{{ d.version || getVersionName(d.version_id) || '—' }}</td>
              <td style="font-size:11px;color:var(--cicd-text-muted);">{{ fmtDate(d.started_at) }}</td>
              <td class="mono">{{ d.duration_seconds != null ? d.duration_seconds + 's' : '—' }}</td>
              <td>
                <div style="display:flex;gap:4px;">
                  <button
                    type="button"
                    class="cicd-btn cicd-btn-ghost cicd-btn-sm"
                    @click="viewLogs(d)"
                    :title="t('agentCicdView.deployments.logs', 'Logs')"
                    :aria-label="t('agentCicdView.deployments.logs', 'Logs')"
                  ><span aria-hidden="true">◫</span></button>
                  <button
                    v-if="d.status === 'running'"
                    type="button"
                    class="cicd-btn cicd-btn-danger cicd-btn-sm"
                    @click="askConfirm('cancel', d)"
                    :title="t('agentCicdView.deployments.cancel', 'Cancel deployment')"
                    :aria-label="t('agentCicdView.deployments.cancel', 'Cancel deployment')"
                  ><span aria-hidden="true">✕</span></button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    </template>

    <!-- Modals -->
    <CreateVersionModal
      v-if="showCreateVersion"
      :agent-did="agentDid"
      @close="showCreateVersion = false"
      @created="showCreateVersion = false"
    />
    <DeploymentModal
      v-if="showDeploy"
      :agent-did="agentDid"
      @close="showDeploy = false"
      @deployed="onDeployed"
    />
    <DeploymentLogsModal
      v-if="logsTarget"
      :deployment="logsTarget"
      :agent-did="agentDid"
      @close="logsTarget = null"
    />
    <ConfirmActionModal
      :show="!!pending"
      :tone="pending?.kind === 'rollback' ? 'warn' : 'danger'"
      :title="pendingTitle"
      :message="pendingMessage"
      :confirm-text="pendingTitle"
      :cancel-text="t('common.cancel', 'Cancel')"
      :busy="pendingBusy"
      @close="pending = null"
      @confirm="runPending"
    />
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useCICDStore } from '@/stores/cicd'
import { authService } from '@/services/auth'
import PipelineBuilder from '@/components/cicd/PipelineBuilder.vue'
import CreateVersionModal from '@/components/cicd/CreateVersionModal.vue'
import DeploymentModal from '@/components/cicd/DeploymentModal.vue'
import DeploymentLogsModal from '@/components/cicd/DeploymentLogsModal.vue'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useI18n } from '@/composables/useI18n'
import '@/components/cicd/tp-cicd.css'
// §pass49 F2 — cross-pollination panel data sources
import { cicdAdminService, type AgentFlag } from '@/services/api/cicdAdmin'
import { apiClient } from '@/services/api/client'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import { useAuthStore } from '@/stores/auth'
dayjs.extend(relativeTime)

const { t, tp } = useI18n()

const route = useRoute()
const agentDid = computed(() => route.params.did as string)
const cicdStore = useCICDStore()

const activeTab = ref('builder')
const showCreateVersion = ref(false)
const showDeploy = ref(false)
const logsTarget = ref<any>(null)

// ── Relay Status ──
const relayStatus = ref<any>(null)
const relayLoading = ref(false)
const relayMessage = ref('')
let relayTimer: ReturnType<typeof setInterval> | null = null

/** §FESUITE (2026-10-09): what the relay read answered when it was not a status. Every answer that was not a 200 drew
 *  one sentence, "No relay answered for this agent. Only an agent deployed behind the relay reports one.": right for the
 *  registry's 404 "No relay configured", and said just the same over a relay that is configured and did not answer (502),
 *  over an address the registry refuses to call (422, its SSRF guard) and over a read that failed (a 5xx, a 401, no
 *  answer at all). Each now says what the registry answered, and a failed read is a read-failed notice with Try again. */
type RelayOutcome = { kind: 'none' | 'silent' | 'refused' | 'failed'; text: string }
const relayOutcome = ref<RelayOutcome | null>(null)
/** a refresh that read no status after one that did: the card keeps what it read last and says the refresh did not */
const relayRefreshFailed = ref('')
/** the page is gone: a refresh a timer or an action scheduled must not ask after it (§FESUITE leave sweep) */
let relayGone = false

/** One read of the relay status: the status, or what the registry answered instead (never a guess). */
async function readRelay(): Promise<{ status: any } | { outcome: RelayOutcome }> {
  let res: Response
  try {
    // 2026-05-07 audit: the relay routes are mounted at /api/v1/{did}/relay/* and the token is the auth service's.
    const token = authService.getAccessToken()
    res = await fetch(`/api/v1/${agentDid.value}/relay/status`, {
      headers: token ? { 'Authorization': `Bearer ${token}` } : {},
    })
  } catch {
    return { outcome: { kind: 'failed', text: t('agentCicdView.relay.failed', 'The relay status could not be read just now.') } }
  }
  const body: any = await res.json().catch(() => null)
  if (res.ok && body && typeof body === 'object') return { status: body }
  const detail = typeof body?.detail === 'string' ? body.detail : ''
  // the registry's own words for an agent whose card names no relay (routers/agent_cicd.py _owned_relay_url)
  if (res.status === 404 && /no relay configured/i.test(detail)) {
    return { outcome: { kind: 'none', text: t('agentCicdView.relay.none', 'No relay answered for this agent. Only an agent deployed behind the relay reports one.') } }
  }
  if (res.status === 502 || res.ok) {
    return { outcome: { kind: 'silent', text: tp('agentCicdView.relay.silent', "This agent's card names a relay address, but no relay status came back: {detail}", { detail: detail || (res.ok ? 'the answer was not a status' : 'HTTP 502') }) } }
  }
  if (res.status === 422) {
    return { outcome: { kind: 'refused', text: tp('agentCicdView.relay.refused', "The registry does not call the relay address on this agent's card: {detail}", { detail: detail || 'HTTP 422' }) } }
  }
  return { outcome: { kind: 'failed', text: tp('agentCicdView.relay.failedHttp', 'The relay status could not be read (HTTP {status}).', { status: res.status }) } }
}

/** One honest ask: an answer starts the refresh while the deployments tab is open; anything else is said once. */
async function checkRelay() {
  relayLoading.value = true
  relayOutcome.value = null
  try {
    const r = await readRelay()
    if (relayGone) return
    if ('status' in r) {
      relayStatus.value = r.status
      relayRefreshFailed.value = ''
      startRelayPoll()
    } else {
      relayStatus.value = null
      relayOutcome.value = r.outcome
    }
  } finally { relayLoading.value = false }
}
function startRelayPoll() {
  if (relayTimer) return
  relayTimer = setInterval(() => { if (activeTab.value === 'deployments') refreshRelay() }, 15000)
}

/** A refresh of a status already shown: a read that brings no status keeps the card and says why. */
async function refreshRelay() {
  if (relayGone) return
  const r = await readRelay()
  if (relayGone) return
  if ('status' in r) {
    relayStatus.value = r.status
    relayRefreshFailed.value = ''
  } else {
    relayRefreshFailed.value = tp('agentCicdView.relay.refreshFailed', 'The last refresh read no status ({what}); the card shows the status read before it.', { what: r.outcome.text })
  }
}

async function relayAction(tool: string) {
  relayLoading.value = true
  relayMessage.value = ''
  try {
    // 2026-05-07 audit: corrected path + token key (see readRelay).
    const token = authService.getAccessToken()
    const res = await fetch(`/api/v1/${agentDid.value}/relay/action`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ tool }),
    })
    const data: any = await res.json().catch(() => null)
    // §FESUITE (2026-10-09): a refusal (404/422/502, the registry's detail) read as a bare "Failed" before: the error
    // body carries `detail`, never `error`. A refusal stays on screen; an outcome the relay reported fades.
    if (!res.ok) {
      relayMessage.value = tp('agentCicdView.relay.actionRefused', 'Not done: {detail}', { detail: (typeof data?.detail === 'string' && data.detail) || `HTTP ${res.status}` })
      return
    }
    relayMessage.value = data?.success ? `${tool.replace('relay_', '')} OK` : (data?.error || 'Failed')
    setTimeout(() => { if (!relayGone) relayMessage.value = '' }, 3000)
    // Refresh after action
    setTimeout(refreshRelay, 2000)
  } catch {
    relayMessage.value = 'Connection error'
  } finally {
    relayLoading.value = false
  }
}

function formatUptime(seconds: number): string {
  if (!seconds) return '—'
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
  return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`
}

// §pass50.1 — fetch the real agent name. Public agent-cards endpoint
// (no auth required); returns name when search term is the agent's UUID
// portion of the DID.
const resolvedAgentName = ref<string>('')
const agentOwnerId = ref<string | null>(null)
let agentLookup: Promise<void> | null = null
async function fetchAgentName(did: string) {
  if (!did) return
  try {
    // §pass50.2 — exact-DID lookup (was: search by UUID prefix which returned
    // 80 federated cards before reaching the actual agent). §FESUITE: through the app's client (the session lives in
    // sessionStorage; this read looked for it in localStorage and always went without one).
    const { data } = await apiClient.get(`/agents/by-did/${encodeURIComponent(did)}`)
    if (data?.name) {
      resolvedAgentName.value = data.name
    }
    if (data?.creator_developer_id != null) agentOwnerId.value = String(data.creator_developer_id)
  } catch (_) { /* ignore — title falls back to truncated DID */ }
}
watch(agentDid, (did) => {
  resolvedAgentName.value = ''
  agentOwnerId.value = null
  if (did) agentLookup = fetchAgentName(did)
}, { immediate: true })
/* §FESUITE: known only once the lookup answered; an admin may look at any agent's page */
const notOwner = computed<boolean>(() => {
  if (agentOwnerId.value == null || authStore.isAdmin) return false
  const u = authStore.user as any
  if (!u) return false
  return ![u.developer_id, u.id].filter((v: any) => v != null).map(String).includes(agentOwnerId.value)
})

const agentName = computed(() => {
  if (resolvedAgentName.value) return resolvedAgentName.value
  const did = agentDid.value
  return did ? did.split(':').pop()?.substring(0, 16) + '…' : 'Agent'
})

const tabs = computed(() => [
  { id: 'builder',     icon: '⬡', label: t('agentCicdView.tabs.builder'),     count: 0 },
  { id: 'pipelines',   icon: '◈', label: t('agentCicdView.tabs.pipelines'),   count: cicdStore.pipelines.length },
  { id: 'versions',    icon: '◎', label: t('agentCicdView.tabs.versions'),    count: cicdStore.versions.length },
  { id: 'deployments', icon: '▶', label: t('agentCicdView.tabs.deployments'), count: cicdStore.deployments.length },
])

// §FESUITE — delete, rollback and cancel ask through the shared dialog (the store used the browser's own confirm()).
type Pending = { kind: 'delete' | 'rollback' | 'cancel'; target: any }
const pending = ref<Pending | null>(null)
const pendingBusy = ref(false)
function askConfirm(kind: Pending['kind'], target: any) { pending.value = { kind, target } }
const esc = (s: unknown) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' } as Record<string, string>)[c])
const pendingTitle = computed(() => {
  const k = pending.value?.kind
  return k === 'delete' ? t('agentCicdView.confirm.deleteTitle', 'Delete pipeline')
    : k === 'rollback' ? t('agentCicdView.confirm.rollbackTitle', 'Roll back to this version')
    : t('agentCicdView.confirm.cancelTitle', 'Cancel deployment')
})
const pendingMessage = computed(() => {
  const p = pending.value
  if (!p) return ''
  if (p.kind === 'delete') return tp('agentCicdView.confirm.deleteBody', 'Delete the pipeline {name}? Its run history goes with it.', { name: `<strong>${esc(p.target.pipeline_name)}</strong>` })
  if (p.kind === 'rollback') return tp('agentCicdView.confirm.rollbackBody', 'Make version {v} the active one again?', { v: `<strong>v${esc(p.target.version)}</strong>` })
  return t('agentCicdView.confirm.cancelBody', 'Stop this deployment while it runs?')
})
async function runPending() {
  const p = pending.value
  if (!p || pendingBusy.value) return
  pendingBusy.value = true
  try {
    if (p.kind === 'delete') await cicdStore.deletePipeline(agentDid.value, p.target.id)
    else if (p.kind === 'rollback') await cicdStore.rollbackVersion(agentDid.value, p.target.id)
    else await cicdStore.cancelDeployment(agentDid.value, p.target.id)
  } catch { /* the store said why in a toast */ } finally {
    pendingBusy.value = false
    pending.value = null
  }
}

const secretCopied = ref(false)
async function copySecret() {
  const s = cicdStore.revealedWebhookSecret?.secret
  if (!s) return
  try { await navigator.clipboard.writeText(s); secretCopied.value = true; setTimeout(() => { secretCopied.value = false }, 1500) } catch { /* the code element stays selectable */ }
}

function editPipeline(p: any) {
  cicdStore.draftPipeline = {
    pipeline_name: p.pipeline_name,
    stages: p.pipeline_config.stages || [],
    trigger_type: p.trigger_type,
    webhook_url: p.webhook_url || '',
  }
  cicdStore.selectPipeline(p)
  activeTab.value = 'builder'
}

// §FESUITE 131 (2026-10-15): the store toasts a refused trigger and rethrows; a click has no one to rethrow to
async function runPipeline(pipelineId: string) {
  try { await cicdStore.triggerPipeline(agentDid.value, pipelineId) } catch { /* toasted by the store */ }
}

function viewLogs(d: any) {
  logsTarget.value = d
  cicdStore.fetchDeploymentLogs(agentDid.value, d.id)
}

function onDeployed() {
  showDeploy.value = false
  activeTab.value = 'deployments'
  cicdStore.fetchDeployments(agentDid.value)
}

function getVersionName(versionId?: string) {
  if (!versionId) return null
  const v = cicdStore.versions.find(x => x.id === versionId)
  return v ? `v${v.version}` : null
}

function fmtDate(d: string) {
  return new Date(d).toLocaleString(appLocale())
}

// §pass49 F2 — Cross-pollination panel: drift, signing keys, flags (read-only for devs)
const showC5 = ref(true)
const driftEvents = ref<any[]>([])
const driftLastPulledAt = ref<string | null>(null)
const driftRefreshMsg = ref('')
const signingKeys = ref<Array<{rotation_seq: number; created_at: string; expires_at?: string | null}>>([])
const flagsForAgent = ref<AgentFlag[]>([])
const rotateMsg = ref('')
const authStore = useAuthStore()
const isAdmin = computed(() => !!(authStore as any).user?.is_admin)
const flagsReadable = ref(false)
const openFlags = computed(() => flagsForAgent.value.filter(f => !f.acknowledged_at))
function hasOpenFlag(type: string): boolean { return openFlags.value.some(f => f.flag_type === type) }
function fromNow(ts: string | null): string { return ts ? dayjs(ts).fromNow() : '—' }

async function loadC5Data() {
  try {
    const did = agentDid.value
    if (!did) return
    // Drift state — relies on /admin/agent-card-drift/{did} when admin, otherwise skip silently
    if (isAdmin.value) {
      try {
        const r = await apiClient.get(`/admin/agent-card-drift/${encodeURIComponent(did)}`)
        const d = r.data || {}
        driftLastPulledAt.value = d.last_pulled_at || null
        driftEvents.value = d.recent_events || d.events || []
      } catch { /* OK — endpoint may not exist on all builds */ }
      try {
        const r = await apiClient.get(`/admin/agents/${encodeURIComponent(did)}/signing-keys`)
        signingKeys.value = (r.data?.keys || r.data?.history || r.data || []) as any
      } catch { signingKeys.value = [] }
      try {
        const r = await cicdAdminService.listFlagsForAgent(did, false, 20)
        flagsForAgent.value = r.flags
        flagsReadable.value = true
      } catch { flagsForAgent.value = []; flagsReadable.value = false }
    }
    // §FESUITE — a member does not ask the admin rail (it answered 403 on every visit and the tiles then read a green
    // "OK" nobody had measured); the tiles say "—" instead.
  } catch (e) {
    console.warn('[AgentCICD F2] cross-pollination load failed', e)
  }
}

async function forceDriftRefresh() {
  driftRefreshMsg.value = 'Refreshing…'
  try {
    await apiClient.post(`/admin/agent-card-drift/${encodeURIComponent(agentDid.value)}/refresh`)
    driftRefreshMsg.value = 'Refresh queued'
    setTimeout(loadC5Data, 1500)
  } catch (e: any) {
    driftRefreshMsg.value = `Refresh failed: ${e?.message || 'error'}`
  }
  setTimeout(() => { driftRefreshMsg.value = '' }, 4000)
}

async function rotateKey() {
  if (!window.confirm('Rotate signing key for this agent? This is permanent (old key expires after grace period).')) return
  rotateMsg.value = ''
  try {
    const r = await apiClient.post(`/admin/agents/${encodeURIComponent(agentDid.value)}/rotate-signing-key`)
    rotateMsg.value = `Rotated — new kid=${r.data?.new_kid || '?'} (PEM shown once in API response)`
    await loadC5Data()
  } catch (e: any) {
    rotateMsg.value = `Rotation failed: ${e?.message || 'error'}`
  }
  setTimeout(() => { rotateMsg.value = '' }, 6000)
}

async function ackFlag(f: AgentFlag) {
  const notes = window.prompt('Optional notes for this acknowledgement:', '')
  try {
    await cicdAdminService.acknowledgeFlag(f.agent_did, f.id, notes || undefined)
    await loadC5Data()
  } catch (e: any) {
    console.warn('ack failed', e)
  }
}

onMounted(async () => {
  await agentLookup
  if (notOwner.value) return
  Promise.all([
    cicdStore.fetchPipelines(agentDid.value),
    cicdStore.fetchVersions(agentDid.value),
    cicdStore.fetchDeployments(agentDid.value),
  ])
  // §FESUITE — the relay status is asked for on the deployments tab (checkRelay), never polled from mount.
  // §pass49 F2
  loadC5Data()
})

onUnmounted(() => {
  relayGone = true
  if (relayTimer) clearInterval(relayTimer)
})
</script>

<style scoped>
/* §pass49 F2 — cross-pollination panel styles */
.cicd-c5-panel {
  display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr));
  gap:12px; margin-bottom:14px;
}
.cicd-c5-section {
  background:rgba(15,22,32,0.5);
  border:1px solid rgba(96,128,192,0.18);
  border-radius:6px; padding:10px 12px;
}
.cicd-c5-section-header {
  display:flex; justify-content:space-between; align-items:center;
  font-size:11px; text-transform:uppercase; letter-spacing:0.08em;
  color:var(--cicd-text-muted, #758296); font-weight:700; margin-bottom:6px;
}
.tile-warn-c5 { border-color: rgba(255,178,69,0.45) !important; }
.relay-card {
  margin-bottom: 16px; padding: 14px 16px; border-radius: 8px;
  background: rgba(10,14,20,0.7); border: 1px solid rgba(255,255,255,0.04);
}
.relay-healthy { border-color: rgba(16,220,129,0.12); }
.relay-down { border-color: rgba(255,107,107,0.12); }

.relay-header { margin-bottom: 10px; }
.relay-title-row { display: flex; align-items: center; gap: 8px; }
.relay-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.relay-dot-up { background: #10dc81; box-shadow: 0 0 6px rgba(16,220,129,0.4); }
.relay-dot-down { background: #ff4444; box-shadow: 0 0 6px rgba(255,68,68,0.4); }
.relay-dot-warn { background: #f5b41e; }
.relay-title { font-size: 10px; font-weight: 700; letter-spacing: 0.15em; color: rgba(255,255,255,0.3); }
.relay-version { font-size: 9px; color: rgba(255,255,255,0.15); font-family: 'Fira Code', monospace; margin-left: auto; }

.relay-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 8px; margin-bottom: 10px;
}
.relay-stat { display: flex; flex-direction: column; gap: 2px; }
.relay-stat-label { font-size: 9px; color: rgba(255,255,255,0.2); letter-spacing: 0.05em; }
.relay-stat-val { font-size: 12px; color: rgba(255,255,255,0.5); font-family: 'Fira Code', monospace; font-weight: 600; }
.relay-val-up { color: rgba(16,220,129,0.8); }
.relay-val-down { color: rgba(255,107,107,0.8); }
.relay-val-warn { color: rgba(245,180,30,0.8); }

.relay-actions { display: flex; gap: 8px; align-items: center; }
.relay-btn-restart {
  background: rgba(var(--nc-primary-rgb),0.08); border: 1px solid rgba(var(--nc-primary-rgb),0.2);
  color: rgba(var(--nc-primary-rgb),0.8); font-size: 11px;
}
.relay-btn-restart:hover { background: rgba(var(--nc-primary-rgb),0.15); }
.relay-btn-start {
  background: rgba(16,220,129,0.08); border: 1px solid rgba(16,220,129,0.2);
  color: rgba(16,220,129,0.8); font-size: 11px;
}
.relay-btn-start:hover { background: rgba(16,220,129,0.15); }
.relay-btn-stop {
  background: rgba(255,107,107,0.06); border: 1px solid rgba(255,107,107,0.15);
  color: rgba(255,107,107,0.7); font-size: 11px;
}
.relay-btn-stop:hover { background: rgba(255,107,107,0.12); }
.relay-loading { font-size: 10px; color: rgba(255,255,255,0.25); font-style: italic; }
.relay-message { font-size: 10px; color: rgba(16,220,129,0.7); font-family: 'Fira Code', monospace; }
</style>
