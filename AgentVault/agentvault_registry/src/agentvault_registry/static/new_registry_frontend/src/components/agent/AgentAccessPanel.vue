<!-- IRONKEY — Agent Access Management panel (STRATEGY §21.2). One reusable core:
     roles + spend policy + effective permissions + mode-aware advisory badge.
     Props: agentDid, mode (owner|admin|readonly). Mounted in AgentProfile (Access tab),
     MyAgents (slide-over), AdminAgents (per-agent). -->
<template>
  <div class="aap">
    <div v-if="loading" class="aap-skel">{{ t('agentAccess.loading', 'Loading access…') }}</div>

    <div v-else-if="error" class="aap-error">
      {{ error }}
      <button class="aap-btn" @click="load">{{ t('agentAccess.retry', 'Retry') }}</button>
    </div>

    <template v-else>
      <!-- mode banner: honest about shadow -->
      <div class="aap-mode" :class="'aap-mode--' + rbacMode">
        <span class="aap-mode-dot"></span>
        <template v-if="rbacMode === 'enforce'">{{ t('agentAccess.mode.enforcePre', 'Enforcement is') }} <strong>{{ t('agentAccess.mode.enforceLive', 'LIVE') }}</strong>{{ t('agentAccess.mode.enforcePost', ': these limits are applied.') }}</template>
        <template v-else-if="rbacMode === 'shadow'">{{ t('agentAccess.mode.shadowPre', 'Advisory,') }} <strong>{{ t('agentAccess.mode.shadowStrong', 'not yet enforced') }}</strong> {{ t('agentAccess.mode.shadowPost', '(shadow mode; would-denies are logged only).') }}</template>
        <template v-else>{{ t('agentAccess.mode.offPre', 'Authorization is') }} <strong>{{ t('agentAccess.mode.offStrong', 'off') }}</strong>{{ t('agentAccess.mode.offPost', ': roles & limits are recorded but inert.') }}</template>
      </div>

      <!-- ROLES -->
      <section class="aap-sec">
        <header class="aap-h">{{ t('agentAccess.roles.title', 'Roles') }}</header>
        <div class="aap-chips">
          <span v-for="r in roles" :key="r" class="aap-chip" :class="{ 'aap-chip--legacy': r === 'legacy-full' }">
            {{ r }}<span v-if="roleExpiry(r)" class="aap-chip-exp" :title="t('agentAccess.roles.expiresTitle', 'expires') + ' ' + roleExpiry(r)">⏳{{ roleExpiryShort(r) }}</span>
            <button v-if="canEdit && r !== 'legacy-full'" class="aap-chip-x" :title="t('agentAccess.roles.remove', 'remove')" @click="toggleRole(r)">×</button>
          </span>
          <span v-if="!roles.length" class="aap-muted">{{ t('agentAccess.roles.none', 'No roles') }}</span>
        </div>
        <div v-if="roles.includes('legacy-full')" class="aap-nudge">
          {{ t('agentAccess.roles.legacyNudge', 'Un-scoped (grandfathered). Assign a role below to limit what this agent can do.') }}
        </div>
        <div v-if="canEdit" class="aap-role-picker">
          <button
            v-for="r in assignableRoles"
            :key="r"
            class="aap-role-opt"
            :class="{ 'aap-role-opt--on': roles.includes(r) }"
            @click="toggleRole(r)"
          >{{ r }}</button>
        </div>
        <!-- B2 — optional time-box applied to the role set on the next save -->
        <label v-if="canEdit" class="aap-field aap-expiry" data-tour="aap-roles-expiry">
          <span>{{ t('agentAccess.roles.expireLabel', 'Roles expire') }} <span class="aap-muted">{{ t('agentAccess.roles.expireHint', '(optional: applies to the whole role set on save; expired roles self-retire)') }}</span></span>
          <input class="aap-in" type="datetime-local" v-model="rolesExpireLocal" @input="savedOk = false" />
        </label>
      </section>

      <!-- SPEND POLICY -->
      <section class="aap-sec">
        <header class="aap-h">{{ t('agentAccess.spend.title', 'Spend policy') }} <span class="aap-muted">{{ t('agentAccess.spend.sub', '(per-tx ceiling · home currency)') }}</span></header>
        <div class="aap-grid2">
          <label class="aap-field">
            <span>{{ t('agentAccess.spend.maxTx', 'Max per transaction') }}</span>
            <input class="aap-in" type="number" min="0" step="any" :disabled="!canEdit"
                   v-model.number="spend.max_per_tx" :placeholder="t('agentAccess.spend.uncapped', 'uncapped')" />
          </label>
          <label class="aap-field">
            <span>{{ t('agentAccess.spend.maxDay', 'Max per day') }} <em>{{ t('agentAccess.spend.maxDayHint', '(net settled, rolling 24 h)') }}</em></span>
            <input class="aap-in" type="number" min="0" step="any" :disabled="!canEdit"
                   v-model.number="spend.max_per_day" :placeholder="t('agentAccess.spend.uncapped', 'uncapped')" />
          </label>
          <label class="aap-field">
            <span>{{ t('agentAccess.spend.cpScope', 'Counterparty scope') }}</span>
            <select class="aap-in" :disabled="!canEdit" v-model="spend.counterparty_mode">
              <option value="any">{{ t('agentAccess.spend.cpAny', 'Any') }}</option>
              <option value="same_registry">{{ t('agentAccess.spend.cpSame', 'Same registry only') }}</option>
              <option value="allowlist">{{ t('agentAccess.spend.cpAllow', 'Allowlist') }}</option>
            </select>
          </label>
          <label class="aap-field">
            <span>{{ t('agentAccess.spend.approvalAbove', 'Require approval above') }} <em>{{ t('agentAccess.spend.approvalHint', '(parks for your approval, Settings → Approvals)') }}</em></span>
            <input class="aap-in" type="number" min="0" step="any" :disabled="!canEdit"
                   v-model.number="spend.require_approval_above" :placeholder="t('agentAccess.spend.none', 'none')" />
          </label>
          <!-- B4/B5 — the richer axes, first-class in the panel -->
          <label class="aap-field">
            <span>{{ t('agentAccess.spend.rate', 'Rate limit') }} <em>{{ t('agentAccess.spend.rateHint', '(spend attempts per rolling hour)') }}</em></span>
            <input class="aap-in" type="number" min="1" step="1" :disabled="!canEdit"
                   v-model.number="spend.rate_per_hour" :placeholder="t('agentAccess.spend.unlimited', 'unlimited')" />
          </label>
          <label class="aap-field">
            <span>{{ t('agentAccess.spend.geo', 'Geo') }} <em>{{ t('agentAccess.spend.geoHint', '(registries where spends may execute, comma-separated names)') }}</em></span>
            <input class="aap-in" type="text" :disabled="!canEdit"
                   v-model="geoAllowText" :placeholder="t('agentAccess.spend.geoPh', 'anywhere (e.g. Frame-C, Frame-B)')" />
          </label>
        </div>
        <p class="aap-note">{{ t('agentAccess.spend.stakingNote', 'Locking units is recoverable and is never counted as spend.') }}</p>
      </section>

      <!-- EFFECTIVE PERMISSIONS -->
      <section class="aap-sec">
        <header class="aap-h">{{ t('agentAccess.perms.title', 'Effective permissions') }} <span class="aap-muted">({{ effective.length }})</span></header>
        <div class="aap-perms">
          <span v-for="p in effective" :key="p" class="aap-perm" :title="permissionTitle(p)">{{ permissionLabel(p) }}</span>
          <span v-if="!effective.length" class="aap-muted">{{ t('agentAccess.perms.none', 'None') }}</span>
        </div>
      </section>

      <!-- B1 — RECENT DENIALS (durable feed from security_audit_logs) -->
      <section class="aap-sec" data-tour="aap-denials">
        <header class="aap-h">
          {{ t('agentAccess.denials.title', 'Recent denials') }}
          <span class="aap-muted">({{ denialsFailed ? '—' : denials.length }} · {{ t('agentAccess.denials.sub', 'what this agent tried and was refused; shadow would-denies included') }})</span>
        </header>
        <div v-if="denialsLoading" class="aap-muted aap-empty">{{ t('agentAccess.denials.loading', 'Loading…') }}</div>
        <ReadFailedNotice v-else-if="denialsFailed" dense :retry="loadDenials" data-testid="aap-denials-failed" />
        <div v-else-if="!denials.length" class="aap-muted aap-empty">{{ t('agentAccess.denials.empty', 'No denials recorded. A quiet feed on an enforcing registry means the agent is operating inside its authority.') }}</div>
        <!-- §MISUSEDETAIL — the shape first: a list of 50 rows that all say the
             same word is not a feed, it is wallpaper. -->
        <div v-if="denialSummary.length" class="aap-deny-sum" data-testid="aap-deny-summary">
          <span v-for="s in denialSummary" :key="s.reason" class="aap-deny-sumchip">
            <b>{{ s.count.toLocaleString(appLocale()) }}</b> {{ reasonWords(s.reason) }}
          </span>
          <span class="aap-muted">{{ tp('agentAccess.denials.window', 'last {d} days', { d: String(denialWindow) }) }}</span>
        </div>
        <div class="aap-denials">
          <div v-for="(d, i) in denials.slice(0, 12)" :key="i" class="aap-deny-row"
               :class="{ 'aap-deny-row--crit': d.severity === 'critical' }">
            <span class="aap-deny-kind" :class="'aap-deny--' + d.action">{{ d.action.replace(/_/g, ' ') }}</span>
            <span v-if="d.outcome" class="aap-deny-chip" :class="'aap-oc--' + d.outcome">{{ d.outcome }}</span>
            <span class="aap-deny-why">{{ denyWhy(d) }}</span>
            <span v-if="d.target" class="aap-deny-target">{{ targetLabel(d) }}</span>
            <span class="aap-deny-when">{{ d.timestamp ? new Date(d.timestamp).toLocaleString(appLocale()) : '' }}</span>
          </div>
        </div>
      </section>

      <!-- DELEGATION & CAPABILITY TOKENS (L3/L4) -->
      <section class="aap-sec">
        <header class="aap-h">
          {{ t('agentAccess.deleg.title', 'Delegation & capability permits') }}
          <span class="aap-muted">(L3/L4 · {{ capsFailed ? '—' : delegMode }})</span>
        </header>

        <!-- delegate meta-permission toggle (the "may issue capability tokens" switch) -->
        <label class="aap-toggle">
          <input type="checkbox" :checked="delegateEnabled" :disabled="!canEdit" @change="toggleDelegate" />
          <span>{{ t('agentAccess.deleg.mayIssue', 'May issue capability permits') }} <span class="aap-muted">{{ t('agentAccess.deleg.mayIssueHintPre', '(grants') }} <code>authz.delegate</code>{{ t('agentAccess.deleg.mayIssueHintPost', ', letting this agent delegate a strictly-weaker slice of its own authority to a sub-agent)') }}</span></span>
        </label>

        <!-- delegation grants: authority delegated TO this agent -->
        <div class="aap-sub">
          <div class="aap-sub-h">{{ t('agentAccess.deleg.grantsTitle', 'On-behalf-of grants') }} <span class="aap-muted">{{ t('agentAccess.deleg.grantsHintPre', '(permissions delegated TO this agent, honored only when its session carries a matching') }} <code>act</code>)</span></div>
          <ReadFailedNotice v-if="grantsFailed" dense :retry="loadDelegation" data-testid="aap-grants-failed" />
          <div v-else-if="!grants.length" class="aap-muted aap-empty">{{ t('agentAccess.deleg.noGrants', 'No delegation grants.') }}</div>
          <div v-for="g in grants" :key="g.id" class="aap-row" :class="{ 'aap-row--dim': g.revoked }">
            <span class="aap-row-principal">{{ g.principal }}</span>
            <span class="aap-row-perms">{{ g.permissions.join(', ') }}</span>
            <span v-if="g.may_redelegate" class="aap-tag">{{ t('agentAccess.deleg.redelegable', 're-delegable') }}</span>
            <span v-if="g.expires_at" class="aap-muted aap-row-exp">{{ t('agentAccess.deleg.exp', 'exp') }} {{ new Date(g.expires_at).toLocaleDateString(appLocale()) }}</span>
            <span v-if="g.revoked" class="aap-muted">{{ t('agentAccess.deleg.revoked', 'revoked') }}</span>
            <button v-else-if="canEdit" class="aap-chip-x aap-row-x" :title="t('agentAccess.deleg.revokeGrant', 'revoke grant')" @click="revokeGrant(g.id)">×</button>
          </div>
          <!-- create grant -->
          <div v-if="canEdit" class="aap-grantform">
            <select class="aap-in aap-in--sm" v-model="newGrant.principal_type" :aria-label="t('agentAccess.deleg.principalType', 'Who receives the grant')">
              <option value="dev">dev</option>
              <option value="org">org</option>
              <option v-if="superAdmin" value="agent">agent</option>
            </select>
            <input class="aap-in aap-in--sm" v-model="newGrant.principal_ref" :readonly="devRefFixed" data-testid="aap-grant-ref"
                   :title="devRefFixed ? t('agentAccess.deleg.devRefYours', 'A dev grant delegates your own authority, so it names you') : undefined"
                   :placeholder="newGrant.principal_type === 'org' ? t('agentAccess.deleg.orgRefPh', 'org slug (one you own or admin)') : t('agentAccess.deleg.refPh', 'id (e.g. 12 for a dev, or an org slug)')" />
            <input class="aap-in aap-in--sm" type="number" min="0" v-model.number="newGrant.ttl_hours" :placeholder="t('agentAccess.deleg.ttlOptPh', 'ttl h (opt)')" />
            <label class="aap-mini"><input type="checkbox" v-model="newGrant.may_redelegate" /> {{ t('agentAccess.deleg.redelegable', 're-delegable') }}</label>
            <button class="aap-btn aap-btn--sm" :disabled="grantBusy || !newGrant.principal_ref || !newGrant.permissions.length" @click="createGrant">
              {{ grantBusy ? '…' : t('agentAccess.deleg.delegateBtn', 'Delegate') }}
            </button>
            <!-- SEC-11: only what a grant from the chosen principal may carry, as the registry serves it -->
            <div class="aap-permpick" data-testid="aap-grant-perms">
              <button v-for="p in grantPermissions" :key="'g'+p" type="button" class="aap-permopt"
                      :class="{ 'aap-permopt--on': newGrant.permissions.includes(p) }" :title="permissionTitle(p)" @click="togglePerm(p)">{{ permissionLabel(p) }}</button>
            </div>
          </div>
        </div>

        <p v-if="refusal?.at === 'deleg'" class="aap-refused" role="alert" data-testid="aap-refused">{{ refusal?.text }}</p>
        <!-- capability tokens: issued/held by this agent (oversight + attenuate + revoke) -->
        <div class="aap-sub">
          <div class="aap-sub-h">{{ t('agentAccess.caps.title', 'Capability permits') }} <span class="aap-muted">{{ t('agentAccess.caps.sub', '(issued or held by this agent · attenuable, budget-bounded, cascade-revocable)') }}</span>
            <!-- retired rows (revoked/expired/exhausted) accumulate forever — keep the live
                 view clean and the history one click away, never silently dropped -->
            <button v-if="retiredCaps.length" type="button" class="aap-chip"
                    style="cursor:pointer" @click="showRetired = !showRetired">
              {{ showRetired ? t('agentAccess.caps.hideRetired', 'hide') : t('agentAccess.caps.showRetired', 'show') }}
              {{ retiredCaps.length }} {{ t('agentAccess.caps.retired', 'retired') }}
            </button>
          </div>
          <ReadFailedNotice v-if="capsFailed" dense :retry="loadDelegation" data-testid="aap-caps-failed" />
          <div v-else-if="!caps.length" class="aap-muted aap-empty">{{ t('agentAccess.caps.none', 'No capability permits.') }}</div>
          <div v-else-if="!visibleCaps.length" class="aap-muted aap-empty">{{ t('agentAccess.caps.allRetired', 'No live permits; the retired ones are behind the toggle above.') }}</div>
          <template v-for="c in visibleCaps" :key="c.id">
            <div class="aap-row" :class="{ 'aap-row--dim': c.status === 'revoked' || c.status === 'expired' }">
              <span class="aap-tag" :class="'aap-tag--' + c.role">{{ c.role }}</span>
              <span class="aap-muted">#{{ c.id }}<template v-if="c.depth"> · d{{ c.depth }}</template></span>
              <span class="aap-row-perms">{{ c.permissions.join(', ') }}</span>
              <span class="aap-row-status" :class="'aap-st--' + c.status">{{ c.status }}</span>
              <span v-if="c.budget_remaining != null" class="aap-muted">{{ c.budget_remaining }}{{ c.currency ? ' ' + c.currency : '' }} {{ t('agentAccess.caps.left', 'left') }}</span>
              <!-- B5, attenuate: anyone holding a live token may derive a strictly-weaker child (SEC-11: not one whose
                   own caveats forbid it, which the registry refuses) -->
              <button v-if="agentActive && (c.status === 'issued' || c.status === 'active') && !c.caveats?.no_redelegate"
                      class="aap-btn aap-btn--sm" data-tour="aap-attenuate" :data-testid="'aap-attenuate-' + c.id"
                      @click="openAttenuate(c)">{{ attFor === c.id ? t('agentAccess.caps.close', 'close') : t('agentAccess.caps.attenuate', 'attenuate') }}</button>
              <button v-if="canEdit && (c.status === 'issued' || c.status === 'active')" class="aap-chip-x aap-row-x" :title="t('agentAccess.caps.revokeTitle', 'revoke (cascades to children)')" @click="revokeCap(c.id)">×</button>
            </div>
            <div v-if="attFor === c.id" class="aap-attform" data-testid="aap-attform">
              <div class="aap-permpick">
                <button v-for="p in c.permissions" :key="'a'+c.id+p" type="button" class="aap-permopt"
                        :class="{ 'aap-permopt--on': att.permissions.includes(p) }"
                        :title="permissionTitle(p)" @click="toggleAttPerm(p)">{{ permissionLabel(p) }}</button>
              </div>
              <!-- SEC-11: every field starts at this token's own limit (equal is within it); the person tightens -->
              <div class="aap-attgrid">
                <input class="aap-in aap-in--sm" type="number" min="0" step="any" v-model.number="att.max_per_tx" :placeholder="t('agentAccess.att.maxTxPh', 'max per tx (opt)')" />
                <input class="aap-in aap-in--sm" type="number" min="1" step="1" v-model.number="att.rate_per_hour" :placeholder="t('agentAccess.att.ratePh', 'rate/h (opt)')" />
                <input class="aap-in aap-in--sm" type="text" v-model="att.geo" :placeholder="t('agentAccess.att.geoPh', 'geo registries, comma (opt)')" />
                <input class="aap-in aap-in--sm" type="text" v-model="att.tools" :placeholder="t('agentAccess.att.toolsPh', 'MCP tools, comma (opt, B6)')" />
                <input class="aap-in aap-in--sm" type="number" min="0" step="any" v-model.number="att.budget_total" data-testid="aap-att-budget"
                       :placeholder="c.budget_remaining != null
                         ? tp('agentAccess.att.budgetLeftPh', 'budget (blank: the {n} left)', { n: String(c.budget_remaining) })
                         : t('agentAccess.issue.budgetPh', 'budget (opt)')" />
                <input class="aap-in aap-in--sm" type="number" min="0" step="1" v-model.number="att.max_uses" data-testid="aap-att-uses"
                       :placeholder="t('agentAccess.att.usesPh', 'max uses (opt)')" />
                <input class="aap-in aap-in--sm" type="number" min="1" max="24" v-model.number="att.ttl_hours" :placeholder="t('agentAccess.att.ttlPh', 'ttl h (1, max 24)')" />
              </div>
              <!-- SEC-11: the phone caveats, for a token that drives a phone -->
              <div v-if="attPhone" class="aap-attgrid" data-testid="aap-att-phone">
                <input class="aap-in aap-in--sm" type="text" v-model="att.phone_apps" data-testid="aap-att-apps"
                       :placeholder="t('agentAccess.att.appsPh', 'phone apps, comma (opt)')" />
                <input class="aap-in aap-in--sm" type="text" v-model="att.phone_domains" data-testid="aap-att-domains"
                       :placeholder="t('agentAccess.att.domainsPh', 'phone network hosts, comma (opt)')" />
                <input class="aap-in aap-in--sm" type="number" min="0" step="1" v-model.number="att.phone_max_actions" data-testid="aap-att-actions"
                       :placeholder="t('agentAccess.att.actionsPh', 'phone actions per session (opt)')" />
                <input class="aap-in aap-in--sm" type="number" min="1" step="1" v-model.number="att.phone_ttl_seconds" data-testid="aap-att-session"
                       :placeholder="t('agentAccess.att.sessionPh', 'phone session seconds (opt)')" />
                <label class="aap-mini" :title="attParent.phone_no_screenshot ? t('agentAccess.att.keptTitle', 'this permit sets it, so the child keeps it') : undefined">
                  <input type="checkbox" v-model="att.phone_no_screenshot" :disabled="!!attParent.phone_no_screenshot" data-testid="aap-att-noshot" />
                  {{ t('agentAccess.att.noShot', 'no screenshots') }}
                </label>
                <label class="aap-mini" :title="attParent.phone_no_network ? t('agentAccess.att.keptTitle', 'this permit sets it, so the child keeps it') : undefined">
                  <input type="checkbox" v-model="att.phone_no_network" :disabled="!!attParent.phone_no_network" data-testid="aap-att-nonet" />
                  {{ t('agentAccess.att.noNet', 'no network') }}
                </label>
              </div>
              <p v-if="attCarried" class="aap-note" data-testid="aap-att-carried">{{ attCarried }}</p>
              <div class="aap-attgrid">
                <button class="aap-btn aap-btn--sm" :disabled="attBusy || !att.permissions.length" data-testid="aap-att-derive" @click="doAttenuate(c)">
                  {{ attBusy ? '…' : t('agentAccess.att.deriveBtn', 'Derive child permit') }}
                </button>
              </div>
              <p class="aap-note">{{ t('agentAccess.att.note', 'The child can only be ≤ this permit on every axis; looser values are refused by the attenuation invariant.') }}</p>
              <div v-if="attResult" class="aap-once">
                <div class="aap-once-h">{{ t('agentAccess.att.onceTitle', 'Child permit, shown ONCE: copy it now') }}</div>
                <code class="aap-once-code">{{ attResult }}</code>
                <button class="aap-btn aap-btn--sm" @click="copy(attResult)">{{ t('agentAccess.copy', 'copy') }}</button>
              </div>
            </div>
          </template>
        </div>

        <p v-if="refusal?.at === 'caps'" class="aap-refused" role="alert" data-testid="aap-refused">{{ refusal?.text }}</p>
        <!-- #143 — ISSUE A ROOT TOKEN (owner rail: developer JWT, no secret pasting).
             Manufactures no authority: the agent must hold authz.delegate and the
             permission set must be ⊆ its live authority — same gate as the agent route. -->
        <div v-if="canEdit" class="aap-sub" data-tour="aap-issue">
          <div class="aap-sub-h">{{ t('agentAccess.issue.title', 'Issue a permit') }} <span class="aap-muted">{{ t('agentAccess.issue.subPre', '(a root') }} <code>att_</code>{{ t('agentAccess.issue.subPost', ' capability: hand a scoped, expiring slice of this agent\'s authority to a holder)') }}</span></div>
          <div v-if="!delegateEnabled" class="aap-muted aap-empty">
            {{ t('agentAccess.issue.gate', 'Enable “May issue capability permits” above first: issuing delegates authority.') }}
          </div>
          <div v-else class="aap-spawnform">
            <input class="aap-in aap-in--sm aap-spawn-name" v-model="issue.holder" :placeholder="t('agentAccess.issue.holderPh', 'holder agent DID (optional, blank = bearer)')" />
            <div class="aap-permpick">
              <button v-for="p in effective" :key="'i'+p" type="button" class="aap-permopt"
                      :class="{ 'aap-permopt--on': issue.permissions.includes(p) }"
                      :title="permissionTitle(p)" @click="toggleIssuePerm(p)">{{ permissionLabel(p) }}</button>
            </div>
            <div class="aap-attgrid">
              <input class="aap-in aap-in--sm" type="number" min="0" step="any" v-model.number="issue.max_per_tx" :placeholder="t('agentAccess.att.maxTxPh', 'max per tx (opt)')" />
              <input class="aap-in aap-in--sm" type="number" min="0" step="any" v-model.number="issue.budget_total" :placeholder="t('agentAccess.issue.budgetPh', 'budget (opt)')" />
              <input class="aap-in aap-in--sm" type="text" v-model="issue.currency" :placeholder="t('agentAccess.issue.currencyPh', 'currency (opt)')" />
              <input class="aap-in aap-in--sm" type="number" min="1" step="1" v-model.number="issue.rate_per_hour" :placeholder="t('agentAccess.att.ratePh', 'rate/h (opt)')" />
              <input class="aap-in aap-in--sm" type="text" v-model="issue.geo" :placeholder="t('agentAccess.att.geoPh', 'geo registries, comma (opt)')" />
              <input class="aap-in aap-in--sm" type="text" v-model="issue.tools" :placeholder="t('agentAccess.att.toolsPh', 'MCP tools, comma (opt, B6)')" />
              <input class="aap-in aap-in--sm" type="number" min="1" max="24" v-model.number="issue.ttl_hours" :placeholder="t('agentAccess.att.ttlPh', 'ttl h (1, max 24)')" />
              <button class="aap-btn aap-btn--sm" :disabled="issueBusy || !issue.permissions.length" @click="doIssue" data-tour="aap-issue-btn">
                {{ issueBusy ? '…' : t('agentAccess.issue.btn', 'Issue permit') }}
              </button>
            </div>
            <p class="aap-note">{{ t('agentAccess.issue.notePre', 'Issued over the owner rail (your developer session): the agent itself must hold') }} <code>authz.delegate</code>{{ t('agentAccess.issue.notePost', ', and you cannot grant what it lacks.') }}</p>
            <div v-if="issueResult" class="aap-once">
              <div class="aap-once-h">{{ t('agentAccess.issue.onceTitle', 'Root permit, shown ONCE: copy it now') }}</div>
              <code class="aap-once-code">{{ issueResult }}</code>
              <button class="aap-btn aap-btn--sm" @click="copy(issueResult)">{{ t('agentAccess.copy', 'copy') }}</button>
            </div>
          </div>
        </div>

        <p v-if="refusal?.at === 'issue'" class="aap-refused" role="alert" data-testid="aap-refused">{{ refusal?.text }}</p>
        <!-- B5 — SPAWN A HAND: mint a scoped sub-agent under this agent (L4 birth token) -->
        <div class="aap-sub" data-tour="aap-spawn">
          <div class="aap-sub-h">{{ t('agentAccess.spawn.title', 'Spawn a hand') }} <span class="aap-muted">{{ t('agentAccess.spawn.sub', '(a scoped sub-agent under this agent: its authority is a birth capability permit, always ≤ the parent)') }}</span></div>
          <div v-if="!agentActive" class="aap-muted aap-empty">
            {{ t('agentAccess.spawn.needsAgent', 'Spawning acts AS this agent: select it in the agent switcher first (its own session signs the birth).') }}
          </div>
          <div v-else-if="!delegateEnabled" class="aap-muted aap-empty">
            {{ t('agentAccess.spawn.gate', 'Enable “May issue capability permits” above first: spawning delegates authority.') }}
          </div>
          <div v-else class="aap-spawnform">
            <input class="aap-in aap-in--sm aap-spawn-name" v-model="spawn.name" :placeholder="t('agentAccess.spawn.namePh', 'hand name (optional)')" />
            <div class="aap-permpick">
              <button v-for="p in effective" :key="'s'+p" type="button" class="aap-permopt"
                      :class="{ 'aap-permopt--on': spawn.permissions.includes(p) }"
                      :title="permissionTitle(p)" @click="toggleSpawnPerm(p)">{{ permissionLabel(p) }}</button>
            </div>
            <div class="aap-attgrid">
              <input class="aap-in aap-in--sm" type="number" min="0" step="any" v-model.number="spawn.max_per_tx" :placeholder="t('agentAccess.att.maxTxPh', 'max per tx (opt)')" />
              <input class="aap-in aap-in--sm" type="number" min="0" step="any" v-model.number="spawn.budget_total" :placeholder="t('agentAccess.issue.budgetPh', 'budget (opt)')" />
              <input class="aap-in aap-in--sm" type="number" min="1" max="24" v-model.number="spawn.ttl_hours" :placeholder="t('agentAccess.spawn.ttlPh', 'ttl h (24, max 24)')" />
              <button class="aap-btn aap-btn--primary aap-btn--sm" :disabled="spawnBusy || !spawn.permissions.length" @click="doSpawn" data-tour="aap-spawn-btn">
                {{ spawnBusy ? t('agentAccess.spawn.busy', 'Spawning…') : t('agentAccess.spawn.btn', 'Spawn hand') }}
              </button>
            </div>
            <div v-if="spawnResult" class="aap-once">
              <div class="aap-once-h">{{ t('agentAccess.spawn.onceTitle', 'Hand born. Credentials shown ONCE: copy them now') }}</div>
              <div class="aap-once-row"><span>DID</span><code class="aap-once-code">{{ spawnResult.child_did }}</code><button class="aap-btn aap-btn--sm" @click="copy(spawnResult.child_did)">{{ t('agentAccess.copy', 'copy') }}</button></div>
              <div class="aap-once-row"><span>client_id</span><code class="aap-once-code">{{ spawnResult.client_id }}</code><button class="aap-btn aap-btn--sm" @click="copy(spawnResult.client_id)">{{ t('agentAccess.copy', 'copy') }}</button></div>
              <div class="aap-once-row"><span>client_secret</span><code class="aap-once-code">{{ spawnResult.client_secret }}</code><button class="aap-btn aap-btn--sm" @click="copy(spawnResult.client_secret)">{{ t('agentAccess.copy', 'copy') }}</button></div>
              <div class="aap-once-row"><span>{{ t('agentAccess.spawn.birthToken', 'birth permit') }}</span><code class="aap-once-code">{{ spawnResult.birth_token }}</code><button class="aap-btn aap-btn--sm" @click="copy(spawnResult.birth_token)">{{ t('agentAccess.copy', 'copy') }}</button></div>
              <p class="aap-note">{{ spawnResult.note }}</p>
            </div>
          </div>
        </div>

        <p v-if="refusal?.at === 'spawn'" class="aap-refused" role="alert" data-testid="aap-refused">{{ refusal?.text }}</p>
        <!-- §FESUITE V0595 (a console gap: API and MCP only before): DELEGATE ACROSS REGISTRIES. A bounded subset of this
             agent's authority, signed here and shipped to an agent on another registry; the delegate spends its own wallet. -->
        <div class="aap-sub" data-testid="aap-xreg">
          <div class="aap-sub-h">{{ t('agentAccess.xreg.title', 'Across registries') }} <span class="aap-muted">{{ t('agentAccess.xreg.sub', '(an agent on another registry acts under your limits, spending its own wallet)') }}</span></div>
          <div v-if="!agentActive" class="aap-muted aap-empty" data-testid="aap-xreg-needs-agent">
            {{ t('agentAccess.xreg.needsAgent', 'Delegating across registries acts AS this agent: select it in the agent switcher first.') }}
          </div>
          <div v-else-if="!delegateEnabled" class="aap-muted aap-empty">
            {{ t('agentAccess.xreg.gate', 'Enable “May issue capability permits” above first: this delegates authority.') }}
          </div>
          <template v-else>
            <div v-if="xregOff" class="aap-muted aap-empty" data-testid="aap-xreg-off">
              {{ t('agentAccess.xreg.off', 'Cross-registry delegation is off on this registry.') }}
            </div>
            <template v-else>
              <ReadFailedNotice v-if="xregFailed" dense :retry="loadXreg" />
              <div v-else-if="xregLoaded && !xreg.length" class="aap-muted aap-empty" data-testid="aap-xreg-none">{{ t('agentAccess.xreg.none', 'Nothing delegated across registries.') }}</div>
              <div v-for="d in xreg" :key="d.credential_id" class="aap-row" :class="{ 'aap-row--dim': d.state !== 'active' }" :data-testid="'aap-xreg-row-' + d.credential_id">
                <code class="aap-row-did" :title="d.delegate_did">{{ shortDid(d.delegate_did) }}</code>
                <span class="aap-muted">{{ hostOf(d.delegate_registry) }}</span>
                <span class="aap-row-perms">{{ d.permissions.join(', ') }}</span>
                <span v-if="d.expires_at" class="aap-muted aap-row-exp">{{ t('agentAccess.deleg.exp', 'exp') }} {{ new Date(d.expires_at).toLocaleDateString(appLocale()) }}</span>
                <span class="aap-tag" :data-testid="'aap-xreg-state-' + d.credential_id">{{ xregStateText(d.state) }}</span>
                <span v-if="d.revoke_delivery && d.revoke_delivery.state !== 'delivered'" class="aap-muted"
                      :title="d.revoke_delivery.last_error || ''" :data-testid="'aap-xreg-delivery-' + d.credential_id">{{ xregDeliveryText(d.revoke_delivery) }}</span>
                <button v-if="d.state === 'active' || d.state === 'not_delivered'" class="aap-chip-x aap-row-x"
                        :title="t('agentAccess.xreg.revoke', 'revoke at their registry')" :disabled="xregBusy" @click="revokeXreg(d)">×</button>
                <button v-else-if="d.state === 'revoked' && xregMaySendAgain(d)" class="aap-chip-x aap-row-x"
                        :data-testid="'aap-xreg-resend-' + d.credential_id"
                        :title="t('agentAccess.xreg.resend', 'send the revoke to their registry again')" :disabled="xregBusy" @click="revokeXreg(d)">↻</button>
              </div>
              <div class="aap-spawnform">
                <input class="aap-in aap-in--sm" v-model="xregNew.delegate_did" data-testid="aap-xreg-did" :placeholder="t('agentAccess.xreg.didPh', 'their agent DID')" />
                <input class="aap-in aap-in--sm" v-model="xregNew.delegate_registry_url" data-testid="aap-xreg-registry" :placeholder="t('agentAccess.xreg.registryPh', 'their registry address (https://...)')" />
                <div class="aap-permpick">
                  <button v-for="p in effective" :key="'x'+p" type="button" class="aap-permopt"
                          :class="{ 'aap-permopt--on': xregNew.permissions.includes(p) }"
                          :title="permissionTitle(p)" @click="toggleXregPerm(p)">{{ permissionLabel(p) }}</button>
                </div>
                <div class="aap-attgrid">
                  <input class="aap-in aap-in--sm" type="number" min="0" step="any" v-model.number="xregNew.max_per_tx" :placeholder="t('agentAccess.att.maxTxPh', 'max per tx (opt)')" />
                  <input class="aap-in aap-in--sm" type="number" min="1" max="720" v-model.number="xregNew.ttl_hours" :placeholder="t('agentAccess.xreg.ttlPh', 'ttl h (24, max 720)')" />
                  <button class="aap-btn aap-btn--primary aap-btn--sm" data-testid="aap-xreg-issue"
                          :disabled="xregBusy || !xregNew.permissions.length || !xregNew.delegate_did.trim() || !xregNew.delegate_registry_url.trim()"
                          @click="issueXreg">{{ xregBusy ? '…' : t('agentAccess.deleg.delegateBtn', 'Delegate') }}</button>
                </div>
                <p v-if="xregNote" class="aap-note" data-testid="aap-xreg-note">{{ xregNote }}</p>
              </div>
            </template>
          </template>
          <p v-if="refusal?.at === 'xreg'" class="aap-refused" role="alert" data-testid="aap-refused">{{ refusal?.text }}</p>
        </div>
        <!-- SUB-AGENT LINEAGE (L4 tree) — lazy: mounted on first expand, then kept alive -->
        <div class="aap-sub">
          <button type="button" class="aap-lineage-toggle" :aria-expanded="lineageOpen" @click="toggleLineage">
            <span class="aap-caret" :class="{ 'aap-caret--open': lineageOpen }" aria-hidden="true">▸</span>
            <span>{{ t('agentAccess.lineage.title', 'Sub-agent lineage') }}</span>
            <span class="aap-muted">{{ t('agentAccess.lineage.sub', '(hands this agent has spawned)') }}</span>
          </button>
          <div v-show="lineageOpen" class="aap-lineage-body">
            <AgentLineageTree v-if="lineageMounted" :agent-did="agentDid" :mode="mode" />
          </div>
        </div>
      </section>

      <div v-if="canEdit" class="aap-actions">
        <button class="aap-btn aap-btn--primary" :disabled="saving" @click="save">
          {{ saving ? t('agentAccess.saving', 'Saving…') : t('agentAccess.saveBtn', 'Save access') }}
        </button>
        <span v-if="savedOk" class="aap-ok">{{ t('agentAccess.saved', 'Saved') }}</span>
        <p v-if="refusal?.at === 'save'" class="aap-refused" role="alert" data-testid="aap-refused">{{ refusal?.text }}</p>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { agentAuthzApi, type SpendPolicy, type AgentDenial } from '@/services/api/agentAuthz'
import { agentDelegationApi, type DelegationGrant, type CapabilityToken, type XRegDelegation, type XRegRevokeDelivery } from '@/services/api/agentDelegation'
import { useAuthStore } from '@/stores/auth'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import { useI18n } from '@/composables/useI18n'
import AgentLineageTree from './AgentLineageTree.vue'
import { refusalText } from './accessRefusal'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { permissionLabel, permissionTitle } from '@/services/permissionLabel'

const { t, tp } = useI18n()

const props = withDefaults(defineProps<{
  agentDid: string
  mode?: 'owner' | 'admin' | 'readonly'
}>(), { mode: 'owner' })

const loading = ref(true)
const error = ref<string | null>(null)
// §FESUITE (2026-10-10): a refused ACTION is said where the action is, and the panel stays as the person left it. Every
// action wrote `error` above, which replaces the whole panel with "error + Retry": a refused save threw away the roles and
// limits the person had just set, and FastAPI's list of refused fields drew as JSON. `error` is the panel's own read now.
type RefusedAt = 'save' | 'deleg' | 'caps' | 'issue' | 'spawn' | 'xreg'
const refusal = ref<{ at: RefusedAt; text: string } | null>(null)
function refuse(at: RefusedAt, e: any, fallback: string) { refusal.value = { at, text: refusalText(e, fallback) } }
const saving = ref(false)
const savedOk = ref(false)
const rbacMode = ref<'off' | 'shadow' | 'enforce'>('off')
const roles = ref<string[]>([])
const effective = ref<string[]>([])
// B2 — per-role expiry detail + the time-box input (datetime-local, empty = permanent)
const roleGrants = ref<{ role: string; expires_at: string | null }[]>([])
const rolesExpireLocal = ref('')
// B1 — durable denial feed
const denials = ref<AgentDenial[]>([])
const denialsLoading = ref(false)
// §FESUITE (V0577): a failed read is not "none": the denials feed (its empty state is an all-clear, "operating inside
// its authority"), the delegation grants, the capability tokens and the delegation mode each say their read failed
const denialsFailed = ref(false)
const grantsFailed = ref(false)
const capsFailed = ref(false)
// §MISUSEDETAIL — the reason shape over a window, and the words for it.
const denialSummary = ref<{ reason: string; count: number }[]>([])
const denialWindow = ref(30)
/** The refusal vocabulary, in words. These are the strings the IRONKEY rails
 *  actually write (measured on frame-c: revoked_reuse 8904,
 *  permission_outside_caveats 3584, holder_mismatch 2295, tool_out_of_scope:*).
 *  An unknown reason renders ITSELF rather than a shrug: a new denial kind must
 *  never become invisible here. */
function reasonWords(raw: string): string {
  const r = String(raw || '')
  if (r.startsWith('tool_out_of_scope:'))
    return tp('agentAccess.denials.rTool', 'tool outside the permit\'s scope ({tool})', { tool: r.split(':')[1] || '' })
  switch (r) {
    case 'revoked_reuse': return t('agentAccess.denials.rRevoked', 'a revoked permit was presented again')
    case 'holder_mismatch': return t('agentAccess.denials.rHolder', 'presented by someone it was not issued to')
    case 'permission_outside_caveats': return t('agentAccess.denials.rCaveat', 'action outside the permit\'s caveats')
    case 'expired': return t('agentAccess.denials.rExpired', 'the permit had expired')
    case 'unknown': return t('agentAccess.denials.rUnknown', 'reason not recorded')
    default: return r.replace(/_/g, ' ')
  }
}
/** One line per row: the why, plus the breaker's own count when it tripped. */
function denyWhy(d: any): string {
  const dt = d?.details || {}
  if (d?.action === 'capability_circuit_breaker_trip') {
    return tp('agentAccess.denials.tripped',
              'circuit breaker: {n} denials in the window, last was {why}',
              { n: String(dt.denials ?? '?'), why: reasonWords(dt.last_reason || 'unknown') })
  }
  if (dt.reason) return reasonWords(dt.reason)
  if (dt.raw) return String(dt.raw)
  return t('agentAccess.denials.rUnknown', 'reason not recorded')
}
function targetLabel(d: any): string {
  if (d?.target_type === 'capability_token') return `permit #${d.target}`
  return `${d?.target_type || ''} ${d?.target || ''}`.trim()
}
function roleExpiry(r: string): string | null {
  const g = roleGrants.value.find(x => x.role === r)
  return g?.expires_at ? new Date(g.expires_at).toLocaleString(appLocale()) : null
}
function roleExpiryShort(r: string): string {
  const g = roleGrants.value.find(x => x.role === r)
  return g?.expires_at ? new Date(g.expires_at).toLocaleDateString(appLocale()) : ''
}
const assignableRoles = ref<string[]>([])
const delegateEnabled = ref(false)
type SpendForm = SpendPolicy & { rate_per_hour?: number | null; geo_allow?: string[] | null }
// §COCKPITDESK (2026-10-15): the form starts from "no limits" for every agent read. It was merged with the answer's
// policy, so an agent without one kept the previous agent's limits on screen (the panel is reused when the page's agent
// changes, /agent-profile/A to /agent-profile/B), and Save wrote them to this agent.
const SPEND_NONE: SpendForm = {
  max_per_tx: null, max_per_day: null, allowed_currencies: null,
  counterparty_mode: 'any', counterparty_allow: null, require_approval_above: null,
  rate_per_hour: null, geo_allow: null,
}
const spend = reactive<SpendForm>({ ...SPEND_NONE })
// B4/B5 — geo_allow edits as a comma string, stored as a list (empty = unconstrained)
const geoAllowText = computed({
  get: () => (spend.geo_allow || []).join(', '),
  set: (v: string) => {
    const list = v.split(',').map(s => s.trim()).filter(Boolean)
    spend.geo_allow = list.length ? list : null
  },
})

// B5 — spawning + attenuation act AS the agent, so they need ITS token: available
// exactly when this panel's agent is the active one in the switcher.
const auth = useAuthStore()
const agentActive = computed(() =>
  (auth as any).activeAgent?.did === props.agentDid && !!(auth as any).agentToken)

const spawn = reactive<{ name: string; permissions: string[]; max_per_tx: number | null;
                         budget_total: number | null; ttl_hours: number | null }>({
  name: '', permissions: [], max_per_tx: null, budget_total: null, ttl_hours: null,
})
const spawnBusy = ref(false)
const spawnResult = ref<any>(null)
function toggleSpawnPerm(p: string) {
  const i = spawn.permissions.indexOf(p)
  if (i >= 0) spawn.permissions.splice(i, 1)
  else spawn.permissions.push(p)
}
// ── §FESUITE V0595: delegations across registries (acts AS this agent: its token, tier.ts) ──
const xreg = ref<XRegDelegation[]>([])
const xregLoaded = ref(false)
const xregFailed = ref(false)
const xregOff = ref(false)
const xregBusy = ref(false)
const xregNote = ref('')
const xregNew = reactive<{ delegate_did: string; delegate_registry_url: string; permissions: string[]; ttl_hours: number; max_per_tx: number | null }>({
  delegate_did: '', delegate_registry_url: '', permissions: [], ttl_hours: 24, max_per_tx: null,
})
function toggleXregPerm(p: string) {
  const i = xregNew.permissions.indexOf(p)
  if (i >= 0) xregNew.permissions.splice(i, 1)
  else xregNew.permissions.push(p)
}
const shortDid = (did: string) => (did.length > 30 ? did.slice(0, 18) + '…' + did.slice(-8) : did)
const hostOf = (url: string | null) => { try { return url ? new URL(url).host : '' } catch { return url || '' } }
function xregStateText(state: XRegDelegation['state']): string {
  return ({
    active: t('agentAccess.xreg.stateActive', 'active'),
    expired: t('agentAccess.xreg.stateExpired', 'expired'),
    revoked: t('agentAccess.xreg.stateRevoked', 'revoked'),
    not_delivered: t('agentAccess.xreg.stateNotDelivered', 'not delivered'),
  } as Record<string, string>)[state] || state
}
// D6-272: the revoke is decided here; this says how its message to their registry stands
function xregDeliveryText(dl: XRegRevokeDelivery): string {
  return ({
    retrying: t('agentAccess.xreg.deliveryRetrying', 'their registry has not taken it yet: sent again until it does'),
    given_up: t('agentAccess.xreg.deliveryGivenUp', 'their registry did not take it: no longer sent'),
    expired: t('agentAccess.xreg.deliveryExpired', 'expired before their registry took it'),
    not_queued: t('agentAccess.xreg.deliveryNotQueued', 'not delivered to their registry'),
  } as Record<string, string>)[dl.state] || dl.state
}
function xregMaySendAgain(d: XRegDelegation): boolean {
  const st = d.revoke_delivery?.state
  return st === 'given_up' || st === 'not_queued'
}
async function loadXreg() {
  if (!agentActive.value || !delegateEnabled.value) return
  xregFailed.value = false
  try {
    const r = await agentDelegationApi.listXreg()
    xreg.value = r.delegations || []
    xregOff.value = false
  } catch (e: any) {
    // the registry says the rail is off: that is an answer, not a failed read
    if (e?.response?.status === 403 && /disabled/i.test(String(e?.response?.data?.detail || ''))) xregOff.value = true
    else xregFailed.value = true
  } finally {
    xregLoaded.value = true
  }
}
async function issueXreg() {
  xregBusy.value = true; refusal.value = null; xregNote.value = ''
  try {
    const r = await agentDelegationApi.issueXreg({
      delegate_did: xregNew.delegate_did.trim(), delegate_registry_url: xregNew.delegate_registry_url.trim(),
      permissions: [...xregNew.permissions], ttl_hours: Math.min(720, Math.max(1, xregNew.ttl_hours || 24)),
      max_per_tx: xregNew.max_per_tx,
    })
    // signed here either way; whether their registry took it is the registry's answer, said as such
    xregNote.value = r.ok
      ? t('agentAccess.xreg.delivered', 'Delegated: their registry has it.')
      : t('agentAccess.xreg.notDelivered', 'Signed here, but their registry did not take it: nothing can use it there.')
    xregNew.delegate_did = ''; xregNew.permissions = []; xregNew.max_per_tx = null
    await loadXreg()
  } catch (e: any) {
    refuse('xreg', e, t('agentAccess.xreg.issueFailed', 'Not delegated.'))
  } finally {
    xregBusy.value = false
  }
}
async function revokeXreg(d: XRegDelegation) {
  if (!d.delegate_registry) return
  xregBusy.value = true; refusal.value = null; xregNote.value = ''
  try {
    const r = await agentDelegationApi.revokeXreg(d.credential_id, d.delegate_registry)
    // D6-272: a revoke is recorded here whatever their registry answered, and their registry asks this one before
    // the delegation is used; the message to it is sent again until it lands
    xregNote.value = r.ok
      ? t('agentAccess.xreg.revokedNote', 'Revoked at their registry.')
      : t('agentAccess.xreg.revokeQueued', 'Revoked here. Their registry asks this one before the delegation is used; the revoke has not reached it yet and is sent again until it does.')
    await loadXreg()
  } catch (e: any) {
    refuse('xreg', e, t('agentAccess.xreg.revokeFailed', 'Not revoked.'))
  } finally {
    xregBusy.value = false
  }
}
watch([agentActive, delegateEnabled], ([a, d]) => { if (a && d) void loadXreg() }, { immediate: true })

async function doSpawn() {
  if (!agentActive.value || !spawn.permissions.length) return
  spawnBusy.value = true; refusal.value = null; spawnResult.value = null
  try {
    const childName = spawn.name || null
    spawnResult.value = await agentDelegationApi.spawn({
      name: childName,
      permissions: [...spawn.permissions],
      ttl_seconds: Math.min(24, spawn.ttl_hours || 24) * 3600,
      budget_total: spawn.budget_total,
      max_per_tx: spawn.max_per_tx,
    })
    // §FEFRAME W1: the child's secret is shown ONCE; save it too, so the hand can be flown from this browser. It lives
    // where its parent lives: the acting agent's foreign registry, or this one (no address).
    try {
      const r = spawnResult.value
      if (r?.child_did && r?.client_id && r?.client_secret) {
        agentCredentialsStore.storeCredentials({
          did: r.child_did, client_id: r.client_id, client_secret: r.client_secret,
          name: childName || undefined,
          registry_url: auth.activeAgentRegistryUrl || undefined,
        })
      }
    } catch { /* the panel still shows the pair */ }
    spawn.name = ''; spawn.permissions = []
    // the new hand should be visible where hands live — open + refresh the lineage
    lineageOpen.value = true
    lineageMounted.value = false
    setTimeout(() => { lineageMounted.value = true }, 50)
    await loadDelegation()
  } catch (e: any) {
    refuse('spawn', e, t('agentAccess.spawn.err', 'Spawn failed'))
  } finally {
    spawnBusy.value = false
  }
}

const attFor = ref<number | null>(null)
const att = reactive<{ permissions: string[]; max_per_tx: number | null;
                       rate_per_hour: number | null; geo: string; tools: string;
                       ttl_hours: number | null; budget_total: number | null; max_uses: number | null;
                       phone_apps: string; phone_domains: string; phone_max_actions: number | null;
                       phone_ttl_seconds: number | null; phone_no_screenshot: boolean; phone_no_network: boolean }>({
  permissions: [], max_per_tx: null, rate_per_hour: null, geo: '', tools: '', ttl_hours: null,
  budget_total: null, max_uses: null, phone_apps: '', phone_domains: '', phone_max_actions: null,
  phone_ttl_seconds: null, phone_no_screenshot: false, phone_no_network: false,
})
const attBusy = ref(false)
const attResult = ref<string>('')
// SEC-11: the form had no field for the phone caveats or the uses bound, so a token bounded on one could not be
// attenuated here (the registry refuses a child that drops a bound its parent sets). The form starts from the parent's
// own limits (the token list carries them), offers those fields, and keeps the parent's limits it has no field for.
const attParent = ref<Record<string, any>>({})
const attPhone = ref(false)
const CARRIED_AXES = ['allowed_currencies', 'counterparty_allow', 'resources_listings', 'operations'] as const
const listText = (v: unknown) => (Array.isArray(v) ? v.join(', ') : '')
const splitList = (s: string) => s.split(',').map((x) => x.trim()).filter(Boolean)
const attCarried = computed(() => {
  const words: Record<string, string> = {
    allowed_currencies: t('agentAccess.att.keptCurrencies', 'currencies'),
    counterparty_allow: t('agentAccess.att.keptCounterparties', 'counterparties'),
    resources_listings: t('agentAccess.att.keptListings', 'listings'),
    operations: t('agentAccess.att.keptOperations', 'operations'),
  }
  const parts = CARRIED_AXES.filter((k) => Array.isArray(attParent.value[k]) && attParent.value[k].length)
    .map((k) => `${words[k]} ${attParent.value[k].join(', ')}`)
  return parts.length ? tp('agentAccess.att.kept', 'Kept from this permit: {list}', { list: parts.join('; ') }) : ''
})

// #143 — root issue over the OWNER rail (developer JWT; parity-gated server-side)
const issue = reactive<{ holder: string; permissions: string[]; max_per_tx: number | null;
                         budget_total: number | null; currency: string;
                         rate_per_hour: number | null; geo: string; tools: string;
                         ttl_hours: number | null }>({
  holder: '', permissions: [], max_per_tx: null, budget_total: null, currency: '',
  rate_per_hour: null, geo: '', tools: '', ttl_hours: null,
})
const issueBusy = ref(false)
const issueResult = ref<string>('')
function toggleIssuePerm(p: string) {
  const i = issue.permissions.indexOf(p)
  if (i >= 0) issue.permissions.splice(i, 1)
  else issue.permissions.push(p)
}
async function doIssue() {
  if (!issue.permissions.length) return
  issueBusy.value = true; refusal.value = null; issueResult.value = ''
  try {
    const caveats: Record<string, any> = { permissions: [...issue.permissions] }
    if (issue.max_per_tx != null) caveats.max_per_tx = issue.max_per_tx
    if (issue.rate_per_hour != null) caveats.rate_per_hour = issue.rate_per_hour
    const geo = issue.geo.split(',').map(s => s.trim()).filter(Boolean)
    if (geo.length) caveats.geo_allow = geo
    const tools = issue.tools.split(',').map(s => s.trim()).filter(Boolean)
    if (tools.length) caveats.tools = tools
    const r = await agentDelegationApi.issueAsOwner(props.agentDid, {
      holder_agent_did: issue.holder.trim() || null,
      caveats,
      budget_total: issue.budget_total,
      currency: issue.currency.trim() || null,
      ttl_seconds: Math.min(24, issue.ttl_hours || 1) * 3600,
    })
    issueResult.value = r.token || ''
    await loadDelegation()
  } catch (e: any) {
    refuse('issue', e, t('agentAccess.issue.err', 'Issue refused'))
  } finally {
    issueBusy.value = false
  }
}
function openAttenuate(c: CapabilityToken) {
  if (attFor.value === c.id) { attFor.value = null; return }
  attFor.value = c.id
  // SEC-11: the child starts as this token on every limit it sets (equal is within it); a blank budget is given what the
  // token has left (SEC-09), and the uses start at what it has left
  const cav = (c.caveats || {}) as Record<string, any>
  attParent.value = cav
  attPhone.value = (c.permissions || []).includes('phone.use') || Object.keys(cav).some((k) => k.startsWith('phone_'))
  att.permissions = [...(c.permissions || [])]
  att.max_per_tx = amountOrNone(cav.max_per_tx); att.rate_per_hour = amountOrNone(cav.rate_per_hour)
  att.geo = listText(cav.geo_allow); att.tools = listText(cav.tools); att.ttl_hours = null
  att.budget_total = null; att.max_uses = c.uses_left ?? null
  att.phone_apps = listText(cav.phone_allowed_apps); att.phone_domains = listText(cav.phone_allowed_domains)
  att.phone_max_actions = amountOrNone(cav.phone_max_actions); att.phone_ttl_seconds = amountOrNone(cav.phone_ttl_seconds)
  att.phone_no_screenshot = !!cav.phone_no_screenshot; att.phone_no_network = !!cav.phone_no_network
  attResult.value = ''
}
function toggleAttPerm(p: string) {
  const i = att.permissions.indexOf(p)
  if (i >= 0) att.permissions.splice(i, 1)
  else att.permissions.push(p)
}
async function doAttenuate(c: CapabilityToken) {
  if (!agentActive.value || !att.permissions.length) return
  attBusy.value = true; refusal.value = null; attResult.value = ''
  try {
    const caveats: Record<string, any> = { permissions: [...att.permissions] }
    // the parent's limits this form has no field for stay the parent's own (a child that drops one is refused)
    for (const k of CARRIED_AXES) {
      const v = attParent.value[k]
      if (Array.isArray(v) && v.length) caveats[k] = [...v]
    }
    const mpt = amountOrNone(att.max_per_tx); if (mpt != null) caveats.max_per_tx = mpt
    const rate = amountOrNone(att.rate_per_hour); if (rate != null) caveats.rate_per_hour = rate
    const geo = splitList(att.geo); if (geo.length) caveats.geo_allow = geo
    const tools = splitList(att.tools); if (tools.length) caveats.tools = tools
    if (attPhone.value) {
      const apps = splitList(att.phone_apps); if (apps.length) caveats.phone_allowed_apps = apps
      const hosts = splitList(att.phone_domains); if (hosts.length) caveats.phone_allowed_domains = hosts
      const acts = amountOrNone(att.phone_max_actions); if (acts != null) caveats.phone_max_actions = acts
      const secs = amountOrNone(att.phone_ttl_seconds); if (secs != null) caveats.phone_ttl_seconds = secs
      if (att.phone_no_screenshot) caveats.phone_no_screenshot = true
      if (att.phone_no_network) caveats.phone_no_network = true
    }
    const body: { caveats: Record<string, any>; ttl_seconds: number; budget_total?: number; max_uses?: number } =
      { caveats, ttl_seconds: Math.min(24, att.ttl_hours || 1) * 3600 }
    const budget = amountOrNone(att.budget_total); if (budget != null) body.budget_total = budget
    const uses = amountOrNone(att.max_uses); if (uses != null) body.max_uses = uses
    const r = await agentDelegationApi.attenuate(c.id, body)
    attResult.value = r.capability_token || r.token || ''
    await loadDelegation()
  } catch (e: any) {
    refuse('caps', e, t('agentAccess.att.err', 'Attenuation refused'))
  } finally {
    attBusy.value = false
  }
}

async function copy(v: string) {
  try { await navigator.clipboard.writeText(v) } catch { /* clipboard denied — value stays visible */ }
}

// L3/L4 — delegation grants + capability-token oversight
const delegMode = ref<'off' | 'shadow' | 'enforce'>('off')
const grants = ref<DelegationGrant[]>([])
const caps = ref<CapabilityToken[]>([])
const showRetired = ref(false)
const LIVE_CAP_STATUSES = ['issued', 'active']
const retiredCaps = computed(() => caps.value.filter(c => !LIVE_CAP_STATUSES.includes(c.status)))
const visibleCaps = computed(() =>
  showRetired.value ? caps.value : caps.value.filter(c => LIVE_CAP_STATUSES.includes(c.status)))
const delegLoaded = ref(false)
const newGrant = reactive<{ principal_type: 'dev' | 'org' | 'agent'; principal_ref: string; permissions: string[]; ttl_hours: number | null; may_redelegate: boolean }>({
  principal_type: 'dev', principal_ref: '', permissions: [], ttl_hours: null, may_redelegate: false,
})
// SEC-11: the grant form offered every catalogue permission, and the registry refuses what the principal may not hand
// out (a developer only what it may grant its agent directly, an organization none of the per-agent ones). It offers
// what the registry serves for the chosen principal (the catalog's delegatable_permissions, the same sets the grant
// route applies), nothing when none is served; a choice the next principal may not carry is dropped, not sent.
const delegatable = ref<Record<string, string[]>>({})
const grantPermissions = computed(() => delegatable.value[newGrant.principal_type] || [])
watch(grantPermissions, (ps) => { newGrant.permissions = newGrant.permissions.filter((p) => ps.includes(p)) })
const grantBusy = ref(false)
// §FESUITE (2026-10-10): a dev grant delegates the authority of the developer it names, and the registry takes only the
// caller's own ("Can only delegate your own dev authority"); an agent principal is admin-only in v1 (is_admin, the super
// flag). The form asked for any developer's id and offered "agent" to everyone, so every value it invited but one was
// refused. It names the viewer now, fixed unless the viewer is a super admin, and offers "agent" only to one.
const myDevId = computed(() => String((auth as any).user?.developer_id ?? (auth as any).user?.id ?? ''))
const superAdmin = computed(() => (auth as any).user?.is_admin === true)
const devRefFixed = computed(() => newGrant.principal_type === 'dev' && !superAdmin.value)
watch([() => newGrant.principal_type, myDevId], ([type], [prevType]) => {
  if (type === 'dev' && (devRefFixed.value || !newGrant.principal_ref)) newGrant.principal_ref = myDevId.value
  else if (type !== 'dev' && prevType === 'dev' && newGrant.principal_ref === myDevId.value) newGrant.principal_ref = ''
}, { immediate: true })

// Sub-agent lineage sub-section — lazy: mount the tree only on first expand,
// then keep it alive and toggle with v-show (no refetch on re-open).
const lineageOpen = ref(false)
const lineageMounted = ref(false)
function toggleLineage() {
  lineageOpen.value = !lineageOpen.value
  if (lineageOpen.value) lineageMounted.value = true
}

const canEdit = computed(() => props.mode === 'owner' || props.mode === 'admin')

function toggleRole(r: string) {
  if (!canEdit.value) return
  const i = roles.value.indexOf(r)
  if (i >= 0) roles.value.splice(i, 1)
  else roles.value.push(r)
  savedOk.value = false
}

// §COCKPITDESK (2026-10-15): every read is for the agent the panel shows when it answers. An answer for an agent the
// panel no longer shows (the page moved on while it was in flight) is dropped; it had filled the form that Save writes to
// the new agent.
let loadSeq = 0
async function load() {
  const did = props.agentDid
  const seq = ++loadSeq
  loading.value = true; error.value = null; savedOk.value = false
  try {
    const [cat, authz] = await Promise.all([
      agentAuthzApi.catalog().catch(() => null),
      agentAuthzApi.get(did),
    ])
    if (seq !== loadSeq || did !== props.agentDid) return
    if (cat) { assignableRoles.value = cat.assignable_roles; rbacMode.value = cat.mode; delegatable.value = cat.delegatable_permissions || {} }
    else rbacMode.value = authz.mode
    roles.value = [...authz.roles]
    effective.value = authz.effective_permissions
    roleGrants.value = authz.role_grants || []
    delegateEnabled.value = !!authz.delegate_enabled
    Object.assign(spend, SPEND_NONE, authz.spend_policy || {})
  } catch (e: any) {
    if (seq !== loadSeq || did !== props.agentDid) return
    error.value = e?.response?.data?.detail || e?.message || t('agentAccess.loadErr', 'Failed to load access')
  } finally {
    if (seq === loadSeq) loading.value = false
  }
  if (seq !== loadSeq || did !== props.agentDid) return
  loadDelegation()
  loadDenials()
}

async function loadDenials() {
  const did = props.agentDid
  denialsLoading.value = true
  denialsFailed.value = false
  try {
    const r: any = await agentAuthzApi.denials(did)
    if (did !== props.agentDid) return
    denialSummary.value = Array.isArray(r?.summary) ? r.summary : []
    if (r?.summary_window_days) denialWindow.value = Number(r.summary_window_days)
    denials.value = r.denials || []
  } catch {
    if (did !== props.agentDid) return
    denials.value = []
    denialSummary.value = []
    denialsFailed.value = true
  } finally {
    if (did === props.agentDid) denialsLoading.value = false
  }
}

async function loadDelegation() {
  const did = props.agentDid
  try {
    const failed = { grants: false, caps: false }
    const [g, c] = await Promise.all([
      agentDelegationApi.listGrants(did).catch(() => { failed.grants = true; return { grants: [] } as any }),
      agentDelegationApi.listCapabilities(did).catch(() => { failed.caps = true; return { tokens: [] } as any }),
    ])
    if (did !== props.agentDid) return
    grantsFailed.value = failed.grants
    capsFailed.value = failed.caps
    grants.value = g.grants || []
    caps.value = c.tokens || []
    // the mode comes with the tokens: a read that failed says nothing about it (it read "off" before)
    if (!capsFailed.value) delegMode.value = (c.mode as any) || 'off'
    delegLoaded.value = true
  } catch { /* delegation surface is best-effort — never blocks the core panel */ }
}

async function toggleDelegate() {
  if (!canEdit.value) return
  const next = !delegateEnabled.value
  try {
    const res = await agentAuthzApi.set(props.agentDid, { delegate_enabled: next })
    delegateEnabled.value = !!res.delegate_enabled
    effective.value = res.effective_permissions
  } catch (e: any) {
    refuse('deleg', e, t('agentAccess.deleg.toggleErr', 'Failed to toggle delegate'))
  }
}

function togglePerm(p: string) {
  const i = newGrant.permissions.indexOf(p)
  if (i >= 0) newGrant.permissions.splice(i, 1)
  else newGrant.permissions.push(p)
}

async function createGrant() {
  if (!newGrant.principal_ref || !newGrant.permissions.length) return
  grantBusy.value = true; refusal.value = null
  try {
    await agentDelegationApi.createGrant(props.agentDid, {
      principal_type: newGrant.principal_type,
      principal_ref: newGrant.principal_ref,
      permissions: [...newGrant.permissions],
      may_redelegate: newGrant.may_redelegate,
      ttl_hours: newGrant.ttl_hours,
    })
    newGrant.principal_ref = newGrant.principal_type === 'dev' ? myDevId.value : ''
    newGrant.permissions = []; newGrant.ttl_hours = null; newGrant.may_redelegate = false
    await loadDelegation()
  } catch (e: any) {
    refuse('deleg', e, 'Failed to create delegation')
  } finally {
    grantBusy.value = false
  }
}

async function revokeGrant(id: number) {
  refusal.value = null
  try { await agentDelegationApi.revokeGrant(id); await loadDelegation() }
  catch (e: any) { refuse('deleg', e, 'Revoke failed') }
}

async function revokeCap(id: number) {
  refusal.value = null
  try { await agentDelegationApi.revokeCapability(props.agentDid, id); await loadDelegation() }
  catch (e: any) { refuse('caps', e, 'Revoke failed') }
}

/** A spend field as the server takes it: a number, or none (an emptied field, or what is not a number). 0 is a number. */
function amountOrNone(v: unknown): number | null {
  if (v === null || v === undefined || (typeof v === 'string' && v.trim() === '')) return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

async function save() {
  saving.value = true; savedOk.value = false; refusal.value = null
  try {
    const body = {
      roles: roles.value.filter(r => r !== 'legacy-full'),
      // B2 — datetime-local is timezone-naive; serialize via Date so the wire carries UTC
      roles_expires_at: rolesExpireLocal.value ? new Date(rolesExpireLocal.value).toISOString() : null,
      // ⚠ _apply_spend UPSERTS every column — an omitted field here WIPES it on save.
      // B5 fixed exactly that for the B4 axes and STILL missed allowed_currencies for a
      // few hours (caught in the pre-compaction gap audit). This body mirrors
      // SpendPolicyIn field-for-field; when adding a policy column, add it HERE too.
      // §FESUITE (2026-10-10): a number field the person emptied holds "" (v-model.number keeps what it cannot parse),
      // which the server refuses as "not a valid number": a cap, once set, could not be taken off here. Empty is none.
      spend_policy: {
        max_per_tx: amountOrNone(spend.max_per_tx), max_per_day: amountOrNone(spend.max_per_day),
        allowed_currencies: spend.allowed_currencies ?? null,
        counterparty_mode: spend.counterparty_mode,
        counterparty_allow: spend.counterparty_allow,
        require_approval_above: amountOrNone(spend.require_approval_above),
        rate_per_hour: amountOrNone(spend.rate_per_hour),
        geo_allow: spend.geo_allow ?? null,
      },
    }
    const res = await agentAuthzApi.set(props.agentDid, body)
    roles.value = [...res.roles]
    effective.value = res.effective_permissions
    roleGrants.value = res.role_grants || []
    Object.assign(spend, SPEND_NONE, res.spend_policy || {})
    savedOk.value = true
  } catch (e: any) {
    refuse('save', e, 'Save failed')
  } finally {
    saving.value = false
  }
}

// a role expiry typed for one agent is not the next agent's (it is part of what Save sends)
watch(() => props.agentDid, () => { rolesExpireLocal.value = ''; void load() })
onMounted(load)
</script>

<style scoped>
.aap { display: flex; flex-direction: column; gap: 1rem; color: var(--text-primary, #cbd5e1); }
.aap-refused { margin: 0.4rem 0 0; font-size: 0.8rem; color: #fca5a5; }
.aap-skel, .aap-error { padding: 1rem; border: 1px solid var(--border-color, #1e293b); border-radius: 10px; background: rgba(15,23,42,.5); }
.aap-error { color: #fca5a5; display: flex; gap: .75rem; align-items: center; }
.aap-mode { display: flex; align-items: center; gap: .5rem; padding: .55rem .8rem; border-radius: 8px; font-size: .85rem; border: 1px solid; }
.aap-mode--shadow { border-color: #b45309; background: rgba(180,83,9,.12); color: #fcd34d; }
.aap-mode--enforce { border-color: #15803d; background: rgba(21,128,61,.14); color: #86efac; }
.aap-mode--off { border-color: #334155; background: rgba(51,65,85,.2); color: #94a3b8; }
.aap-mode-dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; box-shadow: 0 0 8px currentColor; }
.aap-sec { border: 1px solid var(--border-color, #1e293b); border-radius: 10px; padding: .9rem 1rem; background: rgba(15,23,42,.35); }
.aap-h { font-weight: 600; margin-bottom: .6rem; color: var(--text-primary, #e2e8f0); }
.aap-muted { color: #8b97ab; font-size: .82rem; font-weight: 400; }  /* §FESUITE: #64748b was 3.9:1 */
.aap-chips { display: flex; flex-wrap: wrap; gap: .4rem; }
.aap-chip { display: inline-flex; align-items: center; gap: .35rem; padding: .2rem .6rem; border-radius: 999px; background: rgba(6,182,212,.14); border: 1px solid rgba(6,182,212,.4); color: #67e8f9; font-size: .82rem; }
.aap-chip--legacy { background: rgba(180,83,9,.14); border-color: rgba(180,83,9,.5); color: #fcd34d; }
.aap-chip-x { background: none; border: none; color: inherit; cursor: pointer; font-size: 1rem; line-height: 1; padding: 0; }
.aap-nudge { margin-top: .5rem; font-size: .8rem; color: #fcd34d; }
.aap-role-picker { display: flex; flex-wrap: wrap; gap: .4rem; margin-top: .7rem; }
.aap-role-opt { padding: .25rem .7rem; border-radius: 8px; background: transparent; border: 1px solid #334155; color: #94a3b8; cursor: pointer; font-size: .82rem; text-transform: capitalize; }
.aap-role-opt--on { background: rgba(6,182,212,.16); border-color: #06b6d4; color: #67e8f9; }
.aap-grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: .7rem; }
.aap-field { display: flex; flex-direction: column; gap: .25rem; font-size: .8rem; color: #94a3b8; }
/* §MISUSEDETAIL (2026-08-30, his report: "some texts are longer, the boxes not
   all align, 2 are lower") — exactly the two fields whose label carries an <em>
   hint ("Max per day (net settled, rolling 24 h)" and "Require approval above
   (parks for your approval…)"). Their labels wrap to two lines and pushed their
   own input down, so the inputs no longer shared a baseline across the grid row.
   Letting the label take the slack pins every input to the bottom of its cell,
   which stays true whatever the copy does or however a locale translates it. */
.aap-grid2 > .aap-field { justify-content: flex-end; }
.aap-grid2 > .aap-field > span:first-child { flex: 1 1 auto; }
/* …and the last 4px: with the bottoms pinned, the tops still differed because a
   <select> and an <input> with identical padding are not the same height —
   measured 31.8px vs 35.3px in Chromium. Pin the box so both agree exactly. */
.aap-grid2 .aap-in:is(input, select) { height: 35px; box-sizing: border-box; }
.aap-field em { color: #8b97ab; font-style: normal; font-size: .72rem; }
.aap-in { padding: .4rem .55rem; border-radius: 7px; background: rgba(2,6,23,.6); border: 1px solid #334155; color: #e2e8f0; }
.aap-in:disabled { opacity: .6; }
.aap-note { margin: .6rem 0 0; font-size: .76rem; color: #8b97ab; }
.aap-perms { display: flex; flex-wrap: wrap; gap: .3rem; }
.aap-perm { padding: .15rem .5rem; border-radius: 6px; background: rgba(30,41,59,.6); border: 1px solid #334155; color: #cbd5e1; font-size: .74rem; font-family: ui-monospace, monospace; }
.aap-chip-exp { margin-left: .35rem; font-size: .62rem; color: #fbbf24; opacity: .85; }
.aap-expiry { margin-top: .6rem; max-width: 380px; }
.aap-denials { display: flex; flex-direction: column; gap: .3rem; }
.aap-deny-row { display: flex; align-items: baseline; gap: .7rem; flex-wrap: wrap; padding: .3rem .55rem; border: 1px solid rgba(51,65,85,.55); border-radius: 6px; background: rgba(30,41,59,.35); font-size: .72rem; }
.aap-deny-kind { font-family: ui-monospace, monospace; font-size: .66rem; text-transform: uppercase; letter-spacing: .05em; color: #f87171; min-width: 120px; }
.aap-deny--capability_misuse { color: #fbbf24; }
.aap-deny-target { font-family: ui-monospace, monospace; color: #cbd5e1; }
.aap-deny-when { margin-left: auto; color: #8b97ab; font-size: .66rem; }
/* §MISUSEDETAIL — the reason, the outcome and the shape of the feed */
.aap-deny-why { color: #cbd5e1; }
.aap-deny-chip { font-size: .62rem; text-transform: uppercase; letter-spacing: .05em;
  padding: 0 .35rem; border-radius: 4px; border: 1px solid currentColor; }
.aap-oc--denied { color: #fbbf24; }
.aap-oc--revoked { color: #f87171; }
.aap-deny-row--crit { border-color: rgba(248,113,113,.65); background: rgba(127,29,29,.18); }
.aap-deny--capability_circuit_breaker_trip { color: #f87171; }
.aap-deny-sum { display: flex; align-items: baseline; gap: .55rem; flex-wrap: wrap; margin-bottom: .5rem; }
.aap-deny-sumchip { font-size: .72rem; color: #cbd5e1; padding: .15rem .5rem; border-radius: 999px;
  border: 1px solid rgba(51,65,85,.75); background: rgba(30,41,59,.45); }
.aap-deny-sumchip b { color: #fbbf24; font-variant-numeric: tabular-nums; }
.aap-actions { display: flex; align-items: center; gap: .8rem; }
.aap-btn { padding: .45rem .9rem; border-radius: 8px; background: transparent; border: 1px solid #334155; color: #cbd5e1; cursor: pointer; }
.aap-btn--primary { background: linear-gradient(135deg, #0891b2, #0e7490); border-color: #06b6d4; color: #ecfeff; font-weight: 600; }
.aap-btn:disabled { opacity: .5; cursor: default; }
.aap-btn--sm { padding: .3rem .7rem; font-size: .8rem; }
.aap-ok { color: #86efac; font-size: .85rem; }

/* L3/L4 delegation + capability tokens */
.aap-toggle { display: flex; align-items: flex-start; gap: .5rem; font-size: .84rem; color: #cbd5e1; cursor: pointer; margin-bottom: .3rem; }
.aap-toggle input { margin-top: .2rem; }
.aap-toggle code, .aap-sub-h code { font-family: ui-monospace, monospace; font-size: .76rem; color: #67e8f9; background: rgba(6,182,212,.1); padding: 0 .25rem; border-radius: 4px; }
.aap-sub { margin-top: .85rem; padding-top: .7rem; border-top: 1px solid rgba(51,65,85,.5); }
.aap-sub-h { font-size: .82rem; font-weight: 600; color: #cbd5e1; margin-bottom: .5rem; }
.aap-empty { font-size: .8rem; padding: .2rem 0; }
.aap-row { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem; padding: .35rem .5rem; border-radius: 7px; background: rgba(2,6,23,.4); border: 1px solid #1e293b; margin-bottom: .35rem; font-size: .8rem; }
.aap-row--dim { opacity: .5; }
.aap-row-principal { font-family: ui-monospace, monospace; color: #a5b4fc; }
.aap-row-perms { font-family: ui-monospace, monospace; color: #cbd5e1; font-size: .74rem; flex: 1; min-width: 120px; }
.aap-row-exp, .aap-row-status { font-size: .74rem; }
.aap-row-x { margin-left: auto; color: #fca5a5; font-size: 1.1rem; }
.aap-tag { padding: .05rem .4rem; border-radius: 5px; font-size: .68rem; text-transform: uppercase; letter-spacing: .04em; background: rgba(148,163,184,.15); border: 1px solid #334155; color: #94a3b8; }
.aap-tag--issuer { background: rgba(6,182,212,.14); border-color: rgba(6,182,212,.4); color: #67e8f9; }
.aap-tag--holder { background: rgba(139,92,246,.14); border-color: rgba(139,92,246,.4); color: #c4b5fd; }
.aap-st--revoked { color: #fca5a5; } .aap-st--exhausted { color: #fcd34d; }
.aap-st--active, .aap-st--issued { color: #86efac; } .aap-st--expired { color: #94a3b8; }
.aap-grantform { display: flex; flex-wrap: wrap; align-items: center; gap: .4rem; margin-top: .6rem; }
.aap-grantform .aap-in[readonly] { border-style: dashed; cursor: default; }
.aap-in--sm { padding: .3rem .5rem; font-size: .78rem; }
.aap-mini { display: inline-flex; align-items: center; gap: .3rem; font-size: .76rem; color: #94a3b8; }
.aap-permpick { display: flex; flex-wrap: wrap; gap: .25rem; width: 100%; margin-top: .35rem; }
.aap-permopt { padding: .1rem .45rem; border-radius: 6px; background: transparent; border: 1px solid #334155; color: #94a3b8; cursor: pointer; font-size: .7rem; font-family: ui-monospace, monospace; }
.aap-permopt--on { background: rgba(6,182,212,.16); border-color: #06b6d4; color: #67e8f9; }

/* B5 — spawn + attenuate forms and the shown-ONCE credential blocks */
.aap-spawnform { display: flex; flex-direction: column; gap: .5rem; }
.aap-spawn-name { max-width: 300px; }
.aap-attform { margin: -.1rem 0 .5rem 1rem; padding: .55rem .6rem; border: 1px dashed rgba(6,182,212,.35); border-radius: 8px; background: rgba(6,182,212,.05); display: flex; flex-direction: column; gap: .45rem; }
.aap-attgrid { display: flex; flex-wrap: wrap; gap: .4rem; align-items: center; }
.aap-once { margin-top: .4rem; padding: .55rem .65rem; border: 1px solid rgba(251,191,36,.45); border-radius: 8px; background: rgba(251,191,36,.07); display: flex; flex-direction: column; gap: .35rem; }
.aap-once-h { font-size: .78rem; font-weight: 700; color: #fbbf24; letter-spacing: .03em; }
.aap-once-row { display: flex; align-items: center; gap: .5rem; font-size: .74rem; color: #94a3b8; }
.aap-once-row span { min-width: 88px; }
.aap-once-code { font-family: ui-monospace, monospace; font-size: .72rem; color: #e2e8f0; background: rgba(2,6,23,.6); padding: .15rem .4rem; border-radius: 5px; overflow-wrap: anywhere; flex: 1; }

/* Sub-agent lineage collapsible */
.aap-lineage-toggle { display: flex; align-items: center; gap: .45rem; width: 100%; background: none; border: none; padding: 0; color: #cbd5e1; cursor: pointer; font-size: .82rem; font-weight: 600; text-align: left; }
.aap-caret { display: inline-block; color: #8b97ab; font-size: .8rem; transition: transform .15s ease; }
.aap-caret--open { transform: rotate(90deg); }
.aap-lineage-body { margin-top: .6rem; }
</style>
