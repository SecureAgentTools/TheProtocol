<!--
  QUICK ONBOARDING (2026-10-09). His words: "a new view where you can issue simple agent identity. by giving the agent a
  name. get standard valid agent card. the agentbuilder stays as is ... it should list your existing agents and allow to
  initiate password reset from there. with their balances (hidden but unhideable) ... make it beautiful ... new users just
  their identity with quick explanation how to use them with an 'i'."

  /onboarding renders this page; the Agent Builder (/agent-builder, /agent-forge) stays AgentForge.vue. One name in, one
  identity out: a DID, a standard A2A v1.0 card (the console's quick template, the registry's validator asked once) and
  the client ID and secret the agent signs in with, shown once. The rails are the ones the quick agent sheet uses
  (agentApi.create: a bootstrap token, then create_agent), the agents list is GET /developers/me/agents, a reset is
  POST /onboard/agents/{did}/reset-credentials (components/quickOnboarding/ResetCredentialsDialog.vue).

  Decisions live in services/quickOnboarding.ts so each is tested on its own:
    - the FIRST identity is the wallet agent (§WALLETAGENT) only after a read of the person's agents that answered and
      held no live agent; a failed read is not "no agents"
    - the console acts as the new identity only when it acts as no agent now; otherwise the page offers it
    - balances are HIDDEN on every visit (an in-memory switch, no storage key): while hidden none is read and none is in
      the DOM; shown, they are read live in batches of at most 50, and a failed entry reads "unread", never 0
-->
<template>
  <div class="qo-view" data-testid="quick-onboarding" :data-issued="issued ? '1' : '0'">
    <!-- ── hero ─────────────────────────────────────────────────────────────────────────────────────────────── -->
    <header class="qo-hero">
      <div class="qo-hero__mark" aria-hidden="true">
        <Icon name="mdi:card-account-details" class="qo-hero__icon" />
      </div>
      <div class="qo-hero__text">
        <p class="qo-eyebrow">{{ t('quickOnboarding.eyebrow', 'Agent identity') }}</p>
        <div class="qo-hero__titleline">
          <h1 class="qo-title">{{ t('quickOnboarding.title', 'Quick onboarding') }}</h1>
          <button type="button" class="qo-info" :class="{ 'is-open': infoOpen }" :aria-expanded="infoOpen ? 'true' : 'false'"
                  aria-controls="qo-explainer" :aria-label="t('quickOnboarding.info.toggle', 'How to use your agent identity')"
                  data-testid="qo-info-toggle" @click="infoOpen = !infoOpen">
            <Icon name="mdi:information-outline" class="qo-info__icon" />
          </button>
        </div>
        <p class="qo-lead">{{ t('quickOnboarding.lead', 'Name an agent. Get its identity: a DID, a standard A2A agent card and the credentials it signs in with.') }}</p>
      </div>
    </header>

    <!-- ── the "i": how to use the identity ─────────────────────────────────────────────────────────────────── -->
    <Transition name="qo-fold">
      <section v-show="infoOpen" id="qo-explainer" class="qo-explainer" aria-labelledby="qo-explainer-title" data-testid="qo-explainer">
        <h2 id="qo-explainer-title" class="qo-explainer__title">{{ t('quickOnboarding.info.title', 'How to use your agent identity') }}</h2>
        <dl class="qo-explainer__grid">
          <div class="qo-explainer__item">
            <dt class="qo-explainer__term"><Icon name="mdi:fingerprint" class="qo-explainer__icon" />{{ t('quickOnboarding.info.didTerm', 'The DID') }}</dt>
            <dd class="qo-explainer__def">{{ t('quickOnboarding.info.didText', "Its permanent address on the network. Other agents and registries find it, call it and pay it by this name. Names are not unique; the DID is.") }}</dd>
          </div>
          <div class="qo-explainer__item">
            <dt class="qo-explainer__term"><Icon name="mdi:card-account-details" class="qo-explainer__icon" />{{ t('quickOnboarding.info.cardTerm', 'The agent card') }}</dt>
            <dd class="qo-explainer__def">{{ t('quickOnboarding.info.cardText', "Its public description in the standard A2A v1.0 format. It starts with a placeholder endpoint; set your own on the agent's page once the agent runs somewhere.") }}</dd>
          </div>
          <div class="qo-explainer__item">
            <dt class="qo-explainer__term"><Icon name="mdi:key-variant" class="qo-explainer__icon" />{{ t('quickOnboarding.info.credsTerm', 'The credentials') }}</dt>
            <dd class="qo-explainer__def">{{ t('quickOnboarding.info.credsText', "The client ID and the client secret are the agent's sign-in. The secret is shown once. If it is lost, reset it here: a reset issues a new client ID and a new secret, and the old pair stops working.") }}</dd>
          </div>
          <div class="qo-explainer__item">
            <dt class="qo-explainer__term"><Icon name="mdi:swap-horizontal" class="qo-explainer__icon" />{{ t('quickOnboarding.info.useTerm', 'Signing in as the agent') }}</dt>
            <dd class="qo-explainer__def">
              {{ t('quickOnboarding.info.useText', 'Send the pair as a form to the sign-in route below (username is the client ID, password is the client secret), or use the MCP tool named below. The answer carries a short-lived access_token: call the API with it as the agent.') }}
              <span class="qo-explainer__code"><code>POST {{ signInUrl }}</code><code>theprotocol_getAgentToken</code></span>
            </dd>
          </div>
          <div class="qo-explainer__item" data-testid="qo-explainer-discover" :data-bond="bondState">
            <dt class="qo-explainer__term"><Icon name="mdi:magnify" class="qo-explainer__icon" />{{ t('quickOnboarding.info.discoverTerm', 'Listing in Discover') }}</dt>
            <dd class="qo-explainer__def">
              {{ discoverSentence }}
              {{ t('quickOnboarding.info.walletUnlisted', "On this page, an account's first identity becomes its wallet agent and is kept out of Discover: it answers no calls.") }}
            </dd>
          </div>
          <div class="qo-explainer__item">
            <dt class="qo-explainer__term"><Icon name="mdi:wrench" class="qo-explainer__icon" />{{ t('quickOnboarding.info.builderTerm', 'The full builder') }}</dt>
            <dd class="qo-explainer__def">
              {{ t('quickOnboarding.info.builderText', 'Endpoints, skills and pricing are set in the Agent Builder.') }}
              <router-link to="/agent-builder" class="qo-link" data-testid="qo-builder-link">{{ t('quickOnboarding.info.builderLink', 'Open the Agent Builder') }}</router-link>
            </dd>
          </div>
        </dl>
      </section>
    </Transition>

    <!-- ── issue an identity, or the one just issued ───────────────────────────────────────────────────────────── -->
    <section class="qo-panel" :class="{ 'qo-panel--issued': !!issued }" aria-labelledby="qo-issue-title" data-testid="qo-issue-panel">
      <template v-if="!issued">
        <div class="qo-panel__head">
          <h2 id="qo-issue-title" class="qo-panel__title">
            {{ walletMode ? t('quickOnboarding.issue.titleFirst', 'Issue your first identity') : t('quickOnboarding.issue.title', 'Issue an identity') }}
          </h2>
          <p v-if="walletMode" class="qo-panel__sub" data-testid="qo-wallet-note">
            <Icon name="mdi:wallet" class="qo-panel__sub-icon" />
            <span>{{ t('quickOnboarding.issue.walletNote', 'Your first identity becomes your wallet agent: it holds your funds and is not listed in Discover. The name is yours to change.') }}</span>
          </p>
        </div>

        <div v-if="unverified" class="qo-notice qo-notice--warn" role="status" data-testid="qo-unverified">
          <Icon name="mdi:email-outline" class="qo-notice__icon" />
          <div class="qo-notice__body">
            <p class="qo-notice__title">{{ t('quickOnboarding.verify.title', 'Confirm your email address first') }}</p>
            <p class="qo-notice__text">{{ t('quickOnboarding.verify.text', 'This registry issues agent identities to developers who confirmed their email. Open the link in the message it sent you, then come back here.') }}</p>
            <div class="qo-notice__actions">
              <button type="button" class="qo-btn qo-btn--quiet" :disabled="resendState === 'sending'" data-testid="qo-resend" @click="resendVerification">
                <Icon name="mdi:email-outline" class="qo-btn__icon" />
                <span>{{ t('quickOnboarding.verify.resend', 'Send the email again') }}</span>
              </button>
              <button type="button" class="qo-btn qo-btn--quiet" :disabled="recheckBusy" data-testid="qo-recheck" @click="recheck">
                <Icon name="mdi:refresh" class="qo-btn__icon" />
                <span>{{ t('quickOnboarding.verify.recheck', 'I have confirmed it') }}</span>
              </button>
            </div>
            <div class="qo-notice__results" data-testid="qo-verify-status">
              <p v-if="resendState === 'sent'" class="qo-notice__result" data-testid="qo-resend-sent">{{ t('quickOnboarding.verify.sent', 'If your email is still unconfirmed, a new link is on its way: look in your inbox.') }}</p>
              <p v-else-if="resendState === 'failed'" class="qo-notice__result">{{ t('quickOnboarding.verify.sendFailed', 'The email could not be sent just now. Try again in a moment.') }}</p>
              <p v-if="recheckState === 'still'" class="qo-notice__result" data-testid="qo-recheck-still">{{ t('quickOnboarding.verify.still', 'The registry still says the email is not confirmed.') }}</p>
              <p v-else-if="recheckState === 'failed'" class="qo-notice__result" data-testid="qo-recheck-failed">{{ t('quickOnboarding.verify.recheckFailed', 'The registry could not be asked just now. Try again in a moment.') }}</p>
            </div>
          </div>
        </div>

        <form class="qo-issue" novalidate data-testid="qo-issue" @submit.prevent="issue">
          <div class="qo-field">
            <label for="qo-name" class="qo-label">{{ t('quickOnboarding.issue.nameLabel', 'Agent name') }}</label>
            <div class="qo-issue__row">
              <input id="qo-name" ref="nameInput" v-model="agentName" class="qo-input" type="text" maxlength="80" autocomplete="off"
                     spellcheck="false" :placeholder="t('quickOnboarding.issue.namePlaceholder', 'e.g. Research Assistant')"
                     :aria-invalid="nameMsg ? 'true' : 'false'" :aria-describedby="nameMsg ? 'qo-name-msg' : 'qo-name-hint'"
                     :disabled="issuing" data-testid="qo-name" @blur="nameTouched = true" />
              <button type="submit" class="qo-btn qo-btn--primary qo-issue__go" :disabled="issuing || unverified" :aria-busy="issuing ? 'true' : 'false'"
                      data-testid="qo-issue-btn">
                <Icon :name="issuing ? 'mdi:loading' : 'mdi:fingerprint'" class="qo-btn__icon" :class="{ 'qo-spin': issuing }" />
                <span>{{ issuing ? t('quickOnboarding.issue.working', 'Issuing…') : t('quickOnboarding.issue.submit', 'Issue identity') }}</span>
              </button>
            </div>
            <p v-if="nameMsg" id="qo-name-msg" class="qo-field__msg" role="alert" data-testid="qo-name-msg">{{ nameMsg }}</p>
            <p v-else id="qo-name-hint" class="qo-hint">
              {{ t('quickOnboarding.issue.nameHint', '2 to 80 characters. Names need not be unique: the DID is the address. Card handle:') }}
              <code class="qo-hint__code">{{ slugPreview }}</code>
            </p>
          </div>

          <button type="button" class="qo-disclose" :aria-expanded="descOpen ? 'true' : 'false'" aria-controls="qo-desc-field"
                  data-testid="qo-desc-toggle" @click="descOpen = !descOpen">
            <Icon name="mdi:chevron-right" class="qo-disclose__chev" :class="{ 'is-open': descOpen }" />
            <span>{{ t('quickOnboarding.issue.descToggle', 'Add a description (optional)') }}</span>
          </button>
          <div v-show="descOpen" id="qo-desc-field" class="qo-field">
            <label for="qo-desc" class="qo-label">{{ t('quickOnboarding.issue.descLabel', 'Description') }}</label>
            <textarea id="qo-desc" v-model="agentDesc" class="qo-input qo-textarea" rows="2" maxlength="280" :disabled="issuing"
                      :aria-invalid="descMsg ? 'true' : 'false'" :aria-describedby="descMsg ? 'qo-desc-msg' : 'qo-desc-hint'"
                      data-testid="qo-desc" @blur="descTouched = true"></textarea>
            <p v-if="descMsg" id="qo-desc-msg" class="qo-field__msg" role="alert">{{ descMsg }}</p>
            <p v-else id="qo-desc-hint" class="qo-hint">{{ t('quickOnboarding.issue.descHint', 'Shown on its public card. At least 5 characters; leave it empty for a plain default.') }}</p>
          </div>

          <p v-if="issueError" class="qo-error" role="alert" data-testid="qo-issue-error" :data-kind="issueErrorKind">
            <Icon name="mdi:alert-circle-outline" class="qo-error__icon" />
            <span>{{ issueError }}</span>
          </p>
        </form>
      </template>

      <template v-else>
        <h2 id="qo-issue-title" class="sr-only">{{ t('quickOnboarding.result.srTitle', 'The identity you issued') }}</h2>
        <!-- the identity, as a card -->
        <article class="qo-idcard" data-testid="qo-result" :data-did="issued.did" :data-wallet="issued.wallet ? '1' : '0'" aria-labelledby="qo-result-name">
          <div class="qo-idcard__sheen" aria-hidden="true"></div>
          <header class="qo-idcard__band">
            <span class="qo-idcard__eyebrow">{{ t('quickOnboarding.result.eyebrow', 'Agent identity') }}</span>
            <span class="qo-idcard__issuer" data-testid="qo-result-issuer">{{ tp('quickOnboarding.result.issuedBy', 'Issued by {registry} on {date}', { registry: registryName, date: issuedOn }) }}</span>
          </header>
          <div class="qo-idcard__main">
            <div class="qo-idcard__portrait" aria-hidden="true">
              <Icon :name="issued.wallet ? 'mdi:wallet' : 'mdi:fingerprint'" class="qo-idcard__glyph" />
              <span class="qo-idcard__initial">{{ initialOf(issued.name) }}</span>
            </div>
            <div class="qo-idcard__facts">
              <h3 id="qo-result-name" class="qo-idcard__name" tabindex="-1" data-testid="qo-result-name">{{ issued.name }}</h3>
              <p class="qo-idcard__chips">
                <span v-if="issued.wallet" class="qo-chip">{{ t('quickOnboarding.result.walletChip', 'Wallet agent') }}</span>
                <span v-if="actingAsIssued" class="qo-chip qo-chip--live" data-testid="qo-result-acting">{{ t('quickOnboarding.result.actingChip', 'The console acts as it now') }}</span>
              </p>
              <div class="qo-idcard__field">
                <span class="qo-idcard__label">{{ t('quickOnboarding.result.did', 'DID') }}</span>
                <div class="qo-idcard__value-line">
                  <code class="qo-idcard__did" data-testid="qo-result-did">{{ issued.did }}</code>
                  <CopyButton :value="issued.did" :what="t('quickOnboarding.result.didWhat', 'the DID')" quiet />
                </div>
              </div>
            </div>
          </div>
          <div class="qo-idcard__creds">
            <p v-if="issued.reset" class="qo-idcard__reset" role="status" data-testid="qo-result-reset">
              <Icon name="mdi:key-variant" class="qo-idcard__reset-icon" />
              <span>{{ t('quickOnboarding.result.wasReset', 'Its credentials were reset after it was issued: the pair first shown here no longer works. The new secret was shown once, in the reset dialog.') }}</span>
            </p>
            <CredentialsBlock v-else-if="issued.clientId && issued.clientSecret" :client-id="issued.clientId" :client-secret="issued.clientSecret" />
            <p v-else class="qo-error" role="status" data-testid="qo-result-nocreds">
              <Icon name="mdi:alert-circle-outline" class="qo-error__icon" />
              <span>{{ t('quickOnboarding.result.noCreds', 'The registry did not return the credentials. Reset them in Your agents below to get a new pair.') }}</span>
            </p>
          </div>
          <ul class="qo-idcard__notes">
            <li v-if="fundingKindNow" class="qo-idcard__note" :data-kind="fundingKindNow" data-testid="qo-funding">
              <Icon :name="fundingIcon" class="qo-idcard__note-icon" />
              <span>{{ fundingSentence }}</span>
            </li>
            <li v-if="issued.wallet && walletListing" class="qo-idcard__note" data-testid="qo-wallet-listing" :data-listing="walletListing">
              <Icon :name="walletListing === 'unlisted' ? 'mdi:eye-off' : 'mdi:eye'" class="qo-idcard__note-icon" />
              <span>{{ walletListing === 'unlisted' ? t('quickOnboarding.result.walletUnlisted', 'Not listed in Discover: a wallet answers no calls. List it from its page when an agent is attached.') : t('quickOnboarding.result.walletListed', 'Still listed in Discover; hide it from its page if you like.') }}</span>
            </li>
            <li v-if="actState === 'failed'" class="qo-idcard__note" data-kind="failed" data-testid="qo-act-failed">
              <Icon name="mdi:alert-circle-outline" class="qo-idcard__note-icon" />
              <span>{{ t('quickOnboarding.result.actFailed', 'The console could not sign in as this agent just now. Press "Act as this agent" to try again.') }}</span>
            </li>
          </ul>
        </article>

        <!-- its card -->
        <section class="qo-sub" aria-labelledby="qo-card-title" data-testid="qo-card" :data-state="cardState">
          <div class="qo-sub__head">
            <h3 id="qo-card-title" class="qo-sub__title">{{ t('quickOnboarding.card.title', 'Agent card') }} <span class="qo-sub__tag">A2A v1.0</span></h3>
            <span v-if="cardValid" class="qo-valid" data-testid="qo-card-valid">
              <Icon name="mdi:check-decagram" class="qo-valid__icon" />
              <span>{{ t('quickOnboarding.card.valid', 'Valid card') }}</span>
            </span>
          </div>
          <p class="qo-hint">
            {{ t('quickOnboarding.card.lead', "Its public description, as this registry stores it. The endpoint is a placeholder until you set your own on the agent's page.") }}
            <template v-if="cardValid">{{ t('quickOnboarding.card.validNote', "Checked by this registry's card validator.") }}</template>
          </p>
          <ReadFailedNotice v-if="cardState === 'failed'" dense :retry="loadCard" data-testid="qo-card-failed"
                            :text="t('quickOnboarding.card.failed', 'The stored card could not be read just now.')" />
          <p v-else-if="cardState === 'loading'" class="qo-hint" role="status">{{ t('quickOnboarding.card.loading', 'Reading the stored card…') }}</p>
          <JsonViewer v-else-if="card" class="qo-json" :data="card" label="agent-card.json" :default-collapsed="true" max-height="22rem" />
          <div class="qo-sub__actions">
            <button type="button" class="qo-btn qo-btn--quiet" :disabled="!card" data-testid="qo-card-download" @click="downloadCard">
              <Icon name="mdi:download" class="qo-btn__icon" />
              <span>{{ t('quickOnboarding.card.download', 'Download card (.json)') }}</span>
            </button>
            <a :href="exportHref" class="qo-link" target="_blank" rel="noopener noreferrer" data-testid="qo-card-export">
              {{ t('quickOnboarding.card.export', 'Public signed card') }}
              <Icon name="mdi:open-in-new" class="qo-link__icon" />
              <span class="sr-only">{{ t('quickOnboarding.card.newTab', '(opens in a new tab)') }}</span>
            </a>
          </div>
        </section>

        <!-- use it -->
        <section class="qo-sub" aria-labelledby="qo-use-title" data-testid="qo-use">
          <div class="qo-sub__head">
            <h3 id="qo-use-title" class="qo-sub__title">{{ t('quickOnboarding.use.title', 'Use it') }}</h3>
          </div>
          <p class="qo-hint">{{ tp('quickOnboarding.use.lead', 'Sign in as the agent from a shell, then call the API with the access_token it answers. The first line asks for the secret without showing it; the command reads it from {variable} and never contains it.', { variable: '$CLIENT_SECRET' }) }}</p>
          <div class="qo-snippet">
            <pre class="qo-snippet__pre" tabindex="0" role="region" :aria-label="t('quickOnboarding.use.snippetLabel', 'Sign-in command')" data-testid="qo-use-snippet">{{ snippet }}</pre>
            <CopyButton :value="snippet" :what="t('quickOnboarding.use.snippetWhat', 'the sign-in command')" quiet />
          </div>
        </section>

        <div class="qo-result-actions">
          <button type="button" class="qo-btn qo-btn--ghost" data-testid="qo-issue-another" @click="issueAnother">
            <Icon name="mdi:plus" class="qo-btn__icon" />
            <span>{{ t('quickOnboarding.result.another', 'Issue another') }}</span>
          </button>
          <router-link :to="{ name: 'agent-details', params: { agentId: issued.did } }" class="qo-btn qo-btn--ghost" data-testid="qo-open-agent">
            <span>{{ t('quickOnboarding.result.open', 'Open agent') }}</span>
            <Icon name="mdi:arrow-right" class="qo-btn__icon" />
          </router-link>
          <button v-if="!actingAsIssued" type="button" class="qo-btn qo-btn--primary" :disabled="actState === 'busy' || !pairFor(issued)"
                  data-testid="qo-act-as" @click="actAs(issued)">
            <Icon :name="actState === 'busy' ? 'mdi:loading' : 'mdi:swap-horizontal'" class="qo-btn__icon" :class="{ 'qo-spin': actState === 'busy' }" />
            <span>{{ t('quickOnboarding.result.actAs', 'Act as this agent') }}</span>
          </button>
        </div>
      </template>
    </section>

    <!-- ── your agents ────────────────────────────────────────────────────────────────────────────────────────── -->
    <section class="qo-agents" aria-labelledby="qo-agents-title" data-testid="qo-agents" :data-state="agentsState" :data-balances="balancesShown ? 'shown' : 'hidden'"
             :data-refreshing="refreshing ? '1' : '0'">
      <div class="qo-agents__head">
        <div class="qo-agents__titles">
          <h2 id="qo-agents-title" class="qo-agents__title">{{ t('quickOnboarding.agents.title', 'Your agents') }}</h2>
          <!-- a status region, there from the start: a search that changes the list is announced -->
          <p class="qo-agents__count" role="status" aria-atomic="true" data-testid="qo-agents-count">{{ agentsState === 'ready' ? countLine : '' }}</p>
        </div>
        <div class="qo-agents__tools">
          <label class="qo-search" for="qo-search">
            <Icon name="mdi:magnify" class="qo-search__icon" />
            <span class="sr-only">{{ t('quickOnboarding.agents.searchLabel', 'Search your agents by name or DID') }}</span>
            <input id="qo-search" v-model="query" class="qo-search__input" type="search" autocomplete="off" spellcheck="false"
                   :placeholder="t('quickOnboarding.agents.searchPlaceholder', 'Search by name or DID')" data-testid="qo-search" />
          </label>
          <!-- the label names the action (as Pocket's does), so no aria-pressed: "Hide balances, pressed" said the opposite
               of what a person sees. The icon names the action too, like the secret's reveal on this page. -->
          <button type="button" class="qo-eye" :class="{ 'is-on': balancesShown }" :data-shown="balancesShown ? '1' : '0'"
                  data-testid="qo-eye" @click="toggleBalances">
            <Icon :name="balancesShown ? 'mdi:eye-off' : 'mdi:eye'" class="qo-eye__icon" />
            <span>{{ balancesShown ? t('quickOnboarding.agents.hideBalances', 'Hide balances') : t('quickOnboarding.agents.showBalances', 'Show balances') }}</span>
          </button>
        </div>
        <!-- a list read again behind the page (a search, an issue, a reset) says so with a thin bar, not by dimming the
             rows: dimmed, their small text fell below AA. Placed out of the flow, so nothing moves when it comes. -->
        <div v-if="refreshing" class="qo-refresh" aria-hidden="true" data-testid="qo-agents-refreshing"><span class="qo-refresh__bar"></span></div>
      </div>

      <p v-if="slice" class="qo-slice" data-testid="qo-slice">
        <Icon name="mdi:information-outline" class="qo-slice__icon" />
        <span>{{ searched ? t('quickOnboarding.agents.sliceSearch', 'These are the newest matches only. Narrow the search to find the others.') : t('quickOnboarding.agents.slice', 'These are your newest agents only. Search to find older ones.') }}</span>
      </p>

      <div v-if="agentsState === 'loading'" class="qo-skeleton" role="status" data-testid="qo-agents-loading">
        <span class="sr-only">{{ t('quickOnboarding.agents.loading', 'Reading your agents…') }}</span>
        <div v-for="i in 3" :key="i" class="qo-skeleton__row" aria-hidden="true"></div>
      </div>
      <ReadFailedNotice v-else-if="agentsState === 'failed'" :retry="retryAgents" data-testid="qo-agents-failed"
                        :text="t('quickOnboarding.agents.failed', 'Your agents could not be read just now.')" />
      <div v-else-if="!rows.length" class="qo-empty" data-testid="qo-agents-empty">
        <Icon name="mdi:robot-outline" class="qo-empty__icon" />
        <p class="qo-empty__text">{{ searched ? t('quickOnboarding.agents.noMatch', 'No agent matches that search.') : t('quickOnboarding.agents.empty', 'No agents yet. Issue your first identity above: it takes one name.') }}</p>
        <button v-if="!searched && !issued" type="button" class="qo-btn qo-btn--quiet" data-testid="qo-empty-cta" @click="focusName">
          <Icon name="mdi:fingerprint" class="qo-btn__icon" />
          <span>{{ t('quickOnboarding.agents.emptyCta', 'Name your first agent') }}</span>
        </button>
      </div>
      <ul v-else class="qo-list" :aria-busy="refreshing ? 'true' : 'false'">
        <li v-for="a in rows" :key="a.did" class="qo-row" :class="{ 'qo-row--new': a.did === issued?.did }" data-testid="qo-agent-row"
            :data-did="a.did" :data-status="String(a.status || 'active')">
          <div class="qo-row__id">
            <span class="qo-row__avatar" aria-hidden="true">{{ initialOf(a.name) }}</span>
            <div class="qo-row__names">
              <span class="qo-row__name">{{ a.name || t('quickOnboarding.agents.unnamed', 'Unnamed agent') }}</span>
              <span class="qo-row__chips">
                <span v-if="isWalletAgent(a)" class="qo-chip" data-testid="qo-row-wallet">{{ t('quickOnboarding.agents.wallet', 'Wallet') }}</span>
                <span v-if="isSuspended(a.status)" class="qo-chip qo-chip--warn" data-testid="qo-row-suspended">{{ t('quickOnboarding.agents.suspended', 'Suspended') }}</span>
                <span v-if="a.did === activeDid" class="qo-chip qo-chip--live">{{ t('quickOnboarding.agents.acting', 'Acting') }}</span>
              </span>
            </div>
          </div>
          <dl class="qo-row__facts">
            <div class="qo-row__fact qo-row__fact--id">
              <dt class="qo-row__term">{{ t('quickOnboarding.agents.did', 'DID') }}</dt>
              <dd class="qo-row__def">
                <code class="qo-row__code" :title="a.did">{{ shortDid(a.did) }}</code>
                <CopyButton :value="a.did" :what="tp('quickOnboarding.agents.didWhat', 'the DID of {name}', { name: rowName(a) })" icon-only quiet />
              </dd>
            </div>
            <div class="qo-row__fact qo-row__fact--id">
              <dt class="qo-row__term">{{ t('quickOnboarding.agents.clientId', 'Client ID') }}</dt>
              <dd class="qo-row__def">
                <template v-if="a.client_id">
                  <code class="qo-row__code" data-testid="qo-row-client-id">{{ a.client_id }}</code>
                  <CopyButton :value="String(a.client_id)" :what="tp('quickOnboarding.agents.clientIdWhat', 'the client ID of {name}', { name: rowName(a) })" icon-only quiet />
                </template>
                <span v-else class="qo-row__none">{{ t('quickOnboarding.agents.none', 'none') }}</span>
              </dd>
            </div>
            <div class="qo-row__fact">
              <dt class="qo-row__term">{{ t('quickOnboarding.agents.created', 'Created') }}</dt>
              <dd class="qo-row__def">{{ createdOn(a.created_at) }}</dd>
            </div>
            <div class="qo-row__fact">
              <dt class="qo-row__term">{{ t('quickOnboarding.agents.balance', 'Balance') }}</dt>
              <dd class="qo-row__def qo-row__balance" data-testid="qo-row-balance" :data-state="balanceState(a.did)">
                <template v-if="!balancesShown">
                  <span class="qo-mask" aria-hidden="true">{{ MASK }} {{ localCurrency }}</span>
                  <span class="sr-only">{{ t('quickOnboarding.agents.balanceHidden', 'Hidden') }}</span>
                </template>
                <template v-else-if="!balances[a.did]">
                  <span class="qo-shimmer" aria-hidden="true"></span>
                  <span class="sr-only">{{ t('quickOnboarding.agents.balanceReading', 'Reading') }}</span>
                </template>
                <span v-else-if="balances[a.did].state === 'ok'" class="qo-amount" :data-amount="okAmount(a.did)">{{ fmt(okAmount(a.did), 6) }} {{ balances[a.did].currency }}</span>
                <span v-else class="qo-unread" data-testid="qo-row-unread">
                  <span class="qo-unread__word">{{ t('quickOnboarding.agents.unread', 'unread') }}<span class="sr-only">{{ ': ' }}</span></span>
                  <span class="qo-unread__why" data-testid="qo-row-unread-why">{{ unreadReason(a.did) }}</span>
                </span>
              </dd>
            </div>
          </dl>
          <div class="qo-row__actions">
            <button v-if="!isSuspended(a.status)" type="button" class="qo-btn qo-btn--quiet" data-testid="qo-row-reset"
                    :aria-label="tp('quickOnboarding.agents.resetOf', 'Reset credentials of {name}', { name: rowName(a) })" @click="openReset(a)">
              <Icon name="mdi:key-variant" class="qo-btn__icon" />
              <span>{{ t('quickOnboarding.agents.reset', 'Reset credentials') }}</span>
            </button>
            <span v-else class="qo-row__note">{{ t('quickOnboarding.agents.suspendedNoReset', 'Suspended: its credentials cannot be reset') }}</span>
            <router-link :to="{ name: 'agent-details', params: { agentId: a.did } }" class="qo-btn qo-btn--quiet" data-testid="qo-row-open"
                         :aria-label="tp('quickOnboarding.agents.openOf', 'Open {name}', { name: rowName(a) })">
              <span>{{ t('quickOnboarding.agents.open', 'Open') }}</span>
              <Icon name="mdi:chevron-right" class="qo-btn__icon" />
            </router-link>
          </div>
        </li>
      </ul>
    </section>

    <ResetCredentialsDialog :show="!!resetTarget" :agent="resetTarget" @close="resetTarget = null" @reset="onReset" />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import JsonViewer from '@/components/common/JsonViewer.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import CopyButton from '@/components/quickOnboarding/CopyButton.vue'
import CredentialsBlock from '@/components/quickOnboarding/CredentialsBlock.vue'
import ResetCredentialsDialog from '@/components/quickOnboarding/ResetCredentialsDialog.vue'
import { useI18n } from '@/composables/useI18n'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { MASK } from '@/composables/usePrivacy'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
import { useAgentStore } from '@/stores/agents'
import { agentApi } from '@/services/api/agents'
import { apiClient } from '@/services/api/client'
import { authApi } from '@/services/api/auth'
import { developerApi } from '@/services/api/developers'
import { reputationBondApi, type BondConfig } from '@/services/api/reputationBond'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import { agentSlug } from '@/services/agentSlug'
import { isWalletAgent, walletTags } from '@/services/walletAgent'
import { appLocale } from '@/services/appLocale'
import { fmt } from '@/services/cockpit/num'
import { config as appConfig } from '@/config'
import type { CreateAgentDto } from '@/types'
import {
  AGENTS_LIMIT, chunks, classifyBalance, cardFileName, firstIsWallet, fundingKind, isSlice, isSuspended, issueRefusal,
  shortDid, useItSnippet, validationPassed, visibleAgents, type AgentRow, type BalanceView,
} from '@/services/quickOnboarding'

const { t, tp } = useI18n()
const auth = useAuthStore()
const ui = useUIStore()
const { config, localCurrency } = useRegistryConfig()

/** The identity this page just issued, its secret shown once. Declared first: computeds and an immediate watcher below
 *  read it during setup (a ref read above its declaration is a TDZ error that blanks the view). */
interface Issued {
  did: string
  name: string
  clientId: string
  clientSecret: string
  wallet: boolean
  at: Date
  slug: string
  funding: string | undefined
  cardId: string | undefined
  /** its credentials were reset on this page after it was issued: the pair it showed is dead */
  reset?: boolean
}
const issued = ref<Issued | null>(null)

// ── the "i" ───────────────────────────────────────────────────────────────────────────────────────────────────────────
const infoOpen = ref(false)
/** where an agent signs in: this console's own API (a relative base resolves against the page) */
const signInUrl = computed(() => {
  const base = String(appConfig.api.baseURL || '/api/v1').replace(/\/+$/, '')
  try { return new URL(`${base}/auth/agent/token`, window.location.origin).href } catch { return `${base}/auth/agent/token` }
})
const bondCfg = ref<BondConfig | null>(null)
const bondState = ref<'reading' | 'read' | 'failed'>('reading')
async function loadBond() {
  bondState.value = 'reading'
  try { bondCfg.value = await reputationBondApi.getConfig(); bondState.value = 'read' }
  catch { bondCfg.value = null; bondState.value = 'failed' }
}
const discoverSentence = computed(() => {
  const b = bondCfg.value
  if (bondState.value !== 'read' || !b) {
    return t('quickOnboarding.info.discoverUnread', 'Whether this registry asks for a reputation bond before an agent appears in Discover could not be read just now.')
  }
  if (b.mode === 'enforce') {
    return tp('quickOnboarding.info.discoverBond', 'An agent appears in Discover and can offer paid services after it posts a reputation bond of {amount} {currency}.',
      { amount: fmt(b.amount, 6), currency: b.currency || localCurrency.value })
  }
  return t('quickOnboarding.info.discoverNoBond', 'This registry asks for no reputation bond: a listed agent appears in Discover.')
})

// ── the agents ────────────────────────────────────────────────────────────────────────────────────────────────────────
const query = ref('')
const rawRows = ref<AgentRow[]>([])
const rawCount = ref(0)
const agentsState = ref<'loading' | 'failed' | 'ready'>('loading')
const refreshing = ref(false)
const searched = ref(false)
const rows = computed(() => visibleAgents(rawRows.value))
const slice = computed(() => agentsState.value === 'ready' && isSlice(rawCount.value))
/** the account as read without a search: the only read that can say "no agents" (and only when it is not a full page) */
const accountRead = ref<{ ok: boolean; searched: boolean; rows: unknown; rawCount: number }>({ ok: false, searched: false, rows: [], rawCount: 0 })
/** the first read of the account, in flight from the page's mount: an issue waits for it before it decides "wallet" */
let firstRead: Promise<void> | null = null
const countLine = computed(() => {
  const n = rows.value.length
  if (searched.value) return n === 1 ? t('quickOnboarding.agents.matchOne', '1 match') : tp('quickOnboarding.agents.matchMany', '{n} matches', { n })
  return n === 1 ? t('quickOnboarding.agents.countOne', '1 agent') : tp('quickOnboarding.agents.countMany', '{n} agents', { n })
})
const activeDid = computed(() => ((auth.activeAgent as { did?: string } | null)?.did) || '')

let listSeq = 0
async function loadAgents(opts: { quiet?: boolean } = {}) {
  const seq = ++listSeq
  const q = query.value.trim()
  if (opts.quiet && agentsState.value === 'ready') refreshing.value = true
  else agentsState.value = 'loading'
  try {
    const data = await agentApi.getMyAgents({ limit: AGENTS_LIMIT, ...(q ? { q } : {}) })
    if (seq !== listSeq) return
    const arr = (Array.isArray(data) ? data : ((data as { items?: unknown[] })?.items || [])) as AgentRow[]
    rawRows.value = arr
    rawCount.value = arr.length
    searched.value = !!q
    agentsState.value = 'ready'
    if (!q) accountRead.value = { ok: true, searched: false, rows: arr, rawCount: arr.length }
  } catch {
    if (seq !== listSeq) return
    agentsState.value = 'failed'
  } finally {
    if (seq === listSeq) refreshing.value = false
  }
}
function retryAgents() {
  const read = loadAgents()
  // a retry after a failed first read is the account's read now: an issue waits for it the same way
  if (!accountRead.value.ok) firstRead = read
  return read
}

let searchTimer: ReturnType<typeof setTimeout> | null = null
watch(query, () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { void loadAgents({ quiet: true }) }, 350)
})

/** an agent as a person names it in a button's or a copy's accessible name */
function rowName(a: AgentRow): string {
  return (typeof a.name === 'string' && a.name.trim()) || shortDid(a.did)
}
function initialOf(name: unknown): string {
  const s = String(name ?? '').trim()
  const ch = s ? Array.from(s)[0] : ''
  return ch ? ch.toUpperCase() : '#'
}
function createdOn(iso: unknown): string {
  const d = new Date(String(iso ?? ''))
  if (!iso || Number.isNaN(d.getTime())) return t('quickOnboarding.agents.none', 'none')
  try { return new Intl.DateTimeFormat(appLocale(), { dateStyle: 'medium' }).format(d) } catch { return d.toISOString().slice(0, 10) }
}

// ── balances: hidden on every visit, read only while shown ───────────────────────────────────────────────────────────
const balancesShown = ref(false)
const balances = ref<Record<string, BalanceView>>({})
/** DIDs being read now: a list refresh during a reveal must not ask for them a second time */
const balInFlight = new Set<string>()
let balSeq = 0
function balanceState(did: string): 'hidden' | 'reading' | 'ok' | 'unread' {
  if (!balancesShown.value) return 'hidden'
  const v = balances.value[did]
  return !v ? 'reading' : v.state
}
function okAmount(did: string): string {
  const v = balances.value[did]
  return v && v.state === 'ok' ? v.amount : ''
}
/** why a balance is unread, in words: the registry's own sentence for an error entry, the page's words otherwise */
function unreadReason(did: string): string {
  const v = balances.value[did]
  if (!v || v.state !== 'unread') return ''
  switch (v.why) {
    case 'error': return v.detail || t('quickOnboarding.agents.unreadError', 'The registry answered with an error.')
    case 'refused': return tp('quickOnboarding.agents.balanceRefused', 'The registry answered {status}.', { status: v.detail })
    case 'no_answer': return t('quickOnboarding.agents.balanceNoAnswer', 'The registry did not answer.')
    case 'no_number': return t('quickOnboarding.agents.unreadNoNumber', 'The answer carried no number.')
    default: return t('quickOnboarding.agents.unreadNoEntry', 'The registry did not answer for this agent.')
  }
}
/** Read the live balance of every listed agent not read yet (all of them after a reveal), at most 50 per request. */
async function readBalances() {
  if (!balancesShown.value) return
  const seq = balSeq
  const dids = rows.value.map((r) => r.did).filter((d) => !balances.value[d] && !balInFlight.has(d))
  if (!dids.length) return
  const cur = localCurrency.value
  for (const d of dids) balInFlight.add(d)
  try {
    for (const chunk of chunks(dids)) {
      if (seq !== balSeq || !balancesShown.value) return
      await readChunk(chunk, seq, cur)
    }
  } finally {
    // a hide or a new reveal cleared the set already; only this run's own markers go
    if (seq === balSeq) for (const d of dids) balInFlight.delete(d)
  }
}
/** One request of at most 50 DIDs. A refused or unanswered request makes each of its agents unread, with the reason. */
async function readChunk(chunk: string[], seq: number, cur: string) {
  let answer: Record<string, unknown> = {}
  let failure: BalanceView | null = null
  try {
    const res = await developerApi.getAgentBalancesBatch(chunk)
    answer = (res && typeof res === 'object' && res.balances && typeof res.balances === 'object' ? res.balances : {}) as Record<string, unknown>
  } catch (e) {
    const st = (e as { response?: { status?: number } })?.response?.status
    failure = st ? { state: 'unread', why: 'refused', detail: String(st), currency: cur }
      : { state: 'unread', why: 'no_answer', detail: '', currency: cur }
  }
  if (seq !== balSeq || !balancesShown.value) return
  const next = { ...balances.value }
  for (const did of chunk) {
    next[did] = failure ?? classifyBalance(answer[did], cur)
  }
  balances.value = next
}
function toggleBalances() {
  balSeq++
  balInFlight.clear()
  balances.value = {}            // nothing read stays in memory once hidden; a reveal reads fresh
  balancesShown.value = !balancesShown.value
  if (balancesShown.value) void readBalances()
}
// a list that changes while balances are shown (a search, a new identity) reads the ones it does not have yet
watch(() => rows.value.map((r) => r.did).join(','), () => { if (balancesShown.value) void readBalances() })

// ── issue ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
const nameInput = ref<HTMLInputElement | null>(null)
const agentName = ref('')
const agentDesc = ref('')
const descOpen = ref(false)
const nameTouched = ref(false)
const descTouched = ref(false)
const submitted = ref(false)
const issuing = ref(false)
const issueError = ref('')
const issueErrorKind = ref<'' | 'unverified' | 'rate_limited' | 'other'>('')

const walletMode = computed(() => !issued.value && firstIsWallet(accountRead.value))  // `issued` is declared above: an immediate watcher reads this
// §WALLETAGENT: the first identity is the wallet; its name starts as "Wallet", the person's to change
watch(walletMode, (v) => {
  if (v && !agentName.value.trim() && !nameTouched.value) agentName.value = t('quickOnboarding.issue.walletName', 'Wallet')
}, { immediate: true })

const trimmedName = computed(() => agentName.value.trim())
const slugPreview = computed(() => agentSlug(trimmedName.value))
const nameProblem = computed(() => {
  const n = Array.from(trimmedName.value).length
  if (n < 2) return t('quickOnboarding.issue.nameShort', 'Give it a name of at least 2 characters.')
  if (n > 80) return t('quickOnboarding.issue.nameLong', 'Keep the name to 80 characters.')
  return ''
})
/** said after a submit, or after the person typed something and left the field; an untouched empty field is not nagged */
const nameMsg = computed(() => {
  if (submitted.value) return nameProblem.value
  if (nameTouched.value && trimmedName.value !== '') return nameProblem.value
  return ''
})
const descProblem = computed(() => {
  const d = agentDesc.value.trim()
  if (!d) return ''
  if (d.length < 5) return t('quickOnboarding.issue.descShort', 'A description needs at least 5 characters, or leave it empty.')
  return ''
})
const descMsg = computed(() => (descTouched.value || submitted.value) ? descProblem.value : '')

/** the registry refuses an identity to a developer who has not confirmed their email (the profile says so, or the refusal did) */
const unverified = computed(() => (auth.user as { is_verified?: boolean } | null)?.is_verified === false || issueErrorKind.value === 'unverified')

const walletListing = ref<'' | 'unlisted' | 'unchanged'>('')
const actState = ref<'' | 'busy' | 'failed'>('')
const actingAsIssued = computed(() => !!issued.value && activeDid.value === issued.value.did)
const registryName = computed(() => (config.value.registry_name || '').trim() || window.location.hostname)
const issuedOn = computed(() => {
  const d = issued.value?.at
  if (!d) return ''
  try { return new Intl.DateTimeFormat(appLocale(), { dateStyle: 'long' }).format(d) } catch { return d.toISOString().slice(0, 10) }
})
const fundingKindNow = computed(() => fundingKind(issued.value?.funding))
// what happened to the starting balance, never a promise: nothing in the registry pays a partial or a deferred one later
const fundingSentence = computed(() => {
  switch (fundingKindNow.value) {
    case 'credited': return t('quickOnboarding.result.fundingCredited', 'Its starting balance was credited.')
    case 'partial': return t('quickOnboarding.result.fundingPartial', 'Part of its starting balance was credited; the rest could not be.')
    case 'deferred': return t('quickOnboarding.result.fundingDeferred', "No starting balance was credited: this registry's treasury is below its floor.")
    case 'failed': return t('quickOnboarding.result.fundingFailed', 'Its starting balance could not be credited.')
    default: return ''
  }
})
const fundingIcon = computed(() => {
  switch (fundingKindNow.value) {
    case 'credited': return 'mdi:check-circle'
    case 'deferred': return 'mdi:information-outline'
    default: return 'mdi:alert-circle-outline'
  }
})
const snippet = computed(() => useItSnippet(signInUrl.value, issued.value?.clientId || '<client-id>'))
const exportHref = computed(() => {
  const base = String(appConfig.api.baseURL || '/api/v1').replace(/\/+$/, '')
  return issued.value ? `${base}/agents/${encodeURIComponent(issued.value.did)}/card-export` : ''
})

async function issue() {
  submitted.value = true
  if (issuing.value) return
  if (nameProblem.value) { nameInput.value?.focus(); return }
  if (descProblem.value) { descOpen.value = true; await nextTick(); document.getElementById('qo-desc')?.focus(); return }
  if (unverified.value) return
  issuing.value = true
  issueError.value = ''
  issueErrorKind.value = ''
  // the wallet rule needs the account's agents: a press before the first read answered waits for it (the button says
  // "Issuing…"), so a fast first issue on a slow registry does not skip the wallet
  if (!accountRead.value.ok && firstRead) await firstRead.catch(() => { /* a failed read is "no wallet guess" */ })
  const wallet = walletMode.value
  const name = trimmedName.value
  const description = agentDesc.value.trim() || (wallet
    ? t('quickOnboarding.issue.walletDesc', "Wallet agent: holds and moves this account's funds; reusable by any agent attached later.")
    : t('quickOnboarding.issue.defaultDesc', 'Agent identity issued with quick onboarding.'))
  try {
    // one bootstrap token is not double-submit safe: the button stays disabled until this answers
    // the refusals this page says in its own words get no global error toast (a 429 keeps the client's "Rate Limited")
    const created = await agentApi.create({ name, description, capabilities: wallet ? walletTags() : [] } as unknown as CreateAgentDto,
      { expectedStatuses: [400, 403, 409, 422, 429] })
    const stored = agentCredentialsStore.getCredentials(created.did)
    issued.value = {
      did: created.did,
      name,
      clientId: created.client_id || stored?.client_id || '',
      clientSecret: created.client_secret || stored?.client_secret || '',
      wallet,
      at: new Date(),
      slug: created.humanReadableId || agentSlug(name),
      funding: created.initial_funding_status,
      cardId: created.agent_card_id,
    }
    // the account holds a live agent from now on, whatever the list read in flight says: a quick "Issue another" must
    // not make a second wallet
    const born: AgentRow = { did: created.did, name, status: 'active', client_id: created.client_id || null, created_at: new Date().toISOString(),
      card_data: { tags: wallet ? walletTags() : [] } }
    accountRead.value = { ok: true, searched: false, rows: [born, ...visibleAgents(accountRead.value.rows)], rawCount: accountRead.value.rawCount + 1 }
    if (!query.value.trim()) rawRows.value = [born, ...rawRows.value.filter((r) => r?.did !== created.did)]
    agentName.value = ''; agentDesc.value = ''; descOpen.value = false
    nameTouched.value = false; descTouched.value = false; submitted.value = false
    walletListing.value = ''; actState.value = ''
    if (wallet) void markWalletUnlisted(created.did)
    // the surfaces behind the page (the dashboard, Pocket, the switcher's store) learn the population changed
    ui.noteAgentCreated()
    useAgentStore().fetchMyAgents().catch(() => { /* the store owns its own error state */ })
    void loadAgents({ quiet: true })
    void loadCard()
    // the console acts as the new identity only when it acts as no agent now; otherwise the page offers it
    if (!activeDid.value) await actAs(issued.value, { quiet: true })
    await nextTick()
    document.getElementById('qo-result-name')?.focus?.()
  } catch (e) {
    const r = issueRefusal(e)
    issueErrorKind.value = r.kind
    if (r.kind === 'unverified') issueError.value = ''
    else if (r.kind === 'rate_limited') issueError.value = t('quickOnboarding.issue.rateLimited', 'Several identities were issued from this address in the last minute. Wait a minute, then try again.')
    else issueError.value = r.message || t('quickOnboarding.issue.failed', 'The identity could not be issued just now. Try again in a moment.')
  } finally {
    issuing.value = false
  }
}

async function markWalletUnlisted(did: string) {
  try {
    await apiClient.patch(`/agent-cards/${encodeURIComponent(did)}/listing`, { unlisted: true }, { expectedStatuses: [400, 403, 404, 409, 422] })
    if (issued.value?.did === did) walletListing.value = 'unlisted'
  } catch {
    if (issued.value?.did === did) walletListing.value = 'unchanged'
  }
}

/** The pair to act as an identity this page issued: the one it showed, or (after a reset here, which killed that one)
 *  the new pair the reset stored where the console keeps agents' keys. */
function pairFor(it: Issued): { client_id: string; client_secret: string } | null {
  if (it.clientId && it.clientSecret) return { client_id: it.clientId, client_secret: it.clientSecret }
  const stored = agentCredentialsStore.getCredentials(it.did)
  return stored?.client_id && stored?.client_secret ? { client_id: stored.client_id, client_secret: stored.client_secret } : null
}

/** Act as an agent this page issued (QuickAgentModal's three steps: sign in with its pair, adopt it, remember it). */
async function actAs(it: Issued, opts: { quiet?: boolean } = {}) {
  const pair = pairFor(it)
  if (!pair) { actState.value = 'failed'; return }
  actState.value = 'busy'
  const agentForAuth = { did: it.did, name: it.name, client_id: pair.client_id, client_secret: pair.client_secret }
  try {
    const ok = await auth.authenticateAsAgent(agentForAuth)
    if (!ok) { actState.value = 'failed'; return }
    auth.setActiveAgentFromToken(agentForAuth, (auth as unknown as { agentToken: string }).agentToken)
    try { localStorage.setItem('activeAgentId', it.did) } catch { /* storage unavailable: the session still acts as it */ }
    actState.value = ''
    if (!opts.quiet) ui.showSuccess(t('quickOnboarding.result.actingTitle', 'Agent active'), tp('quickOnboarding.result.actingText', 'The console now acts as {name}.', { name: it.name }))
  } catch {
    actState.value = 'failed'
  }
}

function issueAnother() {
  issued.value = null
  card.value = null; cardState.value = 'idle'; cardValid.value = false
  walletListing.value = ''; actState.value = ''
  void nextTick(() => nameInput.value?.focus())
}
function focusName() {
  nameInput.value?.focus()
  let calm = false
  try { calm = !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches } catch { /* no media queries: smooth */ }
  nameInput.value?.scrollIntoView?.({ block: 'center', behavior: calm ? 'auto' : 'smooth' })
}

// ── its card ──────────────────────────────────────────────────────────────────────────────────────────────────────────
const card = ref<Record<string, unknown> | null>(null)
const cardState = ref<'idle' | 'loading' | 'ready' | 'failed'>('idle')
const cardValid = ref(false)
async function loadCard() {
  const it = issued.value
  if (!it) return
  cardState.value = 'loading'
  cardValid.value = false
  try {
    const id = it.cardId || it.did
    const { data } = await apiClient.get(`/agent-cards/${encodeURIComponent(id)}`, { expectedStatuses: [404] })
    if (issued.value?.did !== it.did) return
    const cd = data && typeof data === 'object' ? (data as { card_data?: unknown }).card_data : null
    if (!cd || typeof cd !== 'object') throw new Error('no card')
    card.value = cd as Record<string, unknown>
    cardState.value = 'ready'
    void validateCard(card.value, it.did)
  } catch {
    if (issued.value?.did !== it.did) return
    card.value = null
    cardState.value = 'failed'
  }
}
/** the registry's card validator, asked once; only its positive answer shows (silence is no claim) */
async function validateCard(data: Record<string, unknown>, did: string) {
  try {
    const { data: ans } = await apiClient.post('/utils/validate-card', { card_data: data }, { expectedStatuses: [400, 422] })
    if (issued.value?.did === did) cardValid.value = validationPassed(ans)
  } catch { /* no badge */ }
}
function downloadCard() {
  if (!card.value || !issued.value) return
  const blob = new Blob([JSON.stringify(card.value, null, 2) + '\n'], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = cardFileName(issued.value.slug)
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1500)
}

// ── reset ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
const resetTarget = ref<{ did: string; name?: string | null } | null>(null)
function openReset(a: AgentRow) {
  if (isSuspended(a.status)) return
  resetTarget.value = { did: a.did, name: a.name ?? null }
}
function onReset(v: { did: string; client_id: string }) {
  // the row shows its new client ID at once; the list is read again behind it
  rawRows.value = rawRows.value.map((r) => (r.did === v.did ? { ...r, client_id: v.client_id } : r))
  // the card stops showing the pair it was issued with (dead now) and says why
  if (issued.value?.did === v.did) issued.value = { ...issued.value, clientId: v.client_id, clientSecret: '', reset: true }
  void loadAgents({ quiet: true })
}

// ── verification ──────────────────────────────────────────────────────────────────────────────────────────────────────
const resendState = ref<'' | 'sending' | 'sent' | 'failed'>('')
const recheckBusy = ref(false)
const recheckState = ref<'' | 'still' | 'failed'>('')
/** The registry answers 200 whether it sent a link, found the account already verified, or sent nothing in a cooldown;
 *  the page reads its sentence: "already verified" re-reads the profile, anything else is said conditionally. */
async function resendVerification() {
  const email = (auth.user as { email?: string } | null)?.email
  if (!email) { resendState.value = 'failed'; return }
  resendState.value = 'sending'
  try {
    const ans = await authApi.resendVerification(email)
    if (/already verified/i.test(String(ans?.message ?? ''))) { resendState.value = ''; await recheck(); return }
    resendState.value = 'sent'
  } catch { resendState.value = 'failed' }
}
/** "I have confirmed it": a fresh read of the profile. Only a read that ANSWERED decides: false is "still not
 *  confirmed"; true clears the notice. A read that failed says so and keeps the notice (the cached profile is not the
 *  registry's answer); a read that answered without the field (a registry that does not say) lets the next issue ask
 *  the registry again, which claims nothing. */
async function recheck() {
  recheckBusy.value = true
  recheckState.value = ''
  try {
    const read = await auth.refreshProfile()
    if (read !== true) { recheckState.value = 'failed'; return }
    if ((auth.user as { is_verified?: boolean } | null)?.is_verified === false) { recheckState.value = 'still'; return }
    if (issueErrorKind.value === 'unverified') { issueErrorKind.value = ''; issueError.value = '' }
  } catch {
    recheckState.value = 'failed'
  } finally {
    recheckBusy.value = false
  }
}

onMounted(() => {
  firstRead = loadAgents()
  void loadBond()
})
onBeforeUnmount(() => {
  if (searchTimer) clearTimeout(searchTimer)
  balSeq++
  listSeq++
})
</script>

<style scoped>
/* ── page ────────────────────────────────────────────────────────────────────────────────────────────────────────── */
.qo-view {
  position: relative; z-index: 1;
  max-width: 68rem; margin: 0 auto; padding: 1.75rem 1.5rem 3rem;
  display: flex; flex-direction: column; gap: 1.25rem;
  color: var(--nc-text-primary, #e8eaed);
}
.qo-muted, .qo-hint { color: var(--nc-text-secondary, #9aa0a6); }

/* ── hero ────────────────────────────────────────────────────────────────────────────────────────────────────────── */
.qo-hero { display: flex; align-items: flex-start; gap: 1.1rem; }
.qo-hero__mark {
  flex: 0 0 auto; width: 3.6rem; height: 3.6rem; border-radius: 18px; display: grid; place-items: center;
  background:
    radial-gradient(circle at 30% 25%, rgba(var(--nc-primary-rgb), 0.35), transparent 60%),
    linear-gradient(160deg, rgba(var(--nc-primary-rgb), 0.18), rgba(var(--nc-primary-rgb), 0.04));
  border: 1px solid rgba(var(--nc-primary-rgb), 0.4);
  box-shadow: 0 10px 30px -12px rgba(var(--nc-primary-rgb), 0.55), inset 0 1px 0 rgba(255, 255, 255, 0.08);
}
.qo-hero__icon { font-size: 1.85rem; color: var(--nc-primary-bright, var(--nc-primary)); }
.qo-hero__text { display: flex; flex-direction: column; gap: 0.35rem; min-width: 0; }
.qo-eyebrow {
  margin: 0; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.16em; text-transform: uppercase;
  color: var(--nc-primary-bright, var(--nc-primary));
}
.qo-hero__titleline { display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap; }
.qo-title { margin: 0; font-size: clamp(1.55rem, 1.2rem + 1.2vw, 2rem); font-weight: 750; letter-spacing: -0.015em; line-height: 1.15; }
.qo-info {
  width: 2.25rem; height: 2.25rem; border-radius: 999px; display: grid; place-items: center; cursor: pointer;
  color: var(--nc-primary-bright, var(--nc-primary)); background: rgba(var(--nc-primary-rgb), 0.08);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.35);
  transition: background var(--nc-duration-fast, 200ms) ease, transform var(--nc-duration-fast, 200ms) ease;
}
.qo-info:hover { background: rgba(var(--nc-primary-rgb), 0.16); }
.qo-info.is-open { background: rgba(var(--nc-primary-rgb), 0.2); box-shadow: 0 0 0 4px rgba(var(--nc-primary-rgb), 0.12); }
.qo-info:focus-visible { outline: 2px solid var(--nc-primary-bright, var(--nc-primary)); outline-offset: 2px; }
.qo-info__icon { font-size: 1.2rem; }
.qo-lead { margin: 0; max-width: 62ch; font-size: 1rem; line-height: 1.6; color: var(--nc-text-secondary, #9aa0a6); }

/* ── the "i" panel ───────────────────────────────────────────────────────────────────────────────────────────────── */
.qo-explainer {
  border-radius: 16px; padding: 1.25rem 1.35rem;
  background: linear-gradient(180deg, rgba(var(--nc-primary-rgb), 0.07), rgba(255, 255, 255, 0.015));
  border: 1px solid rgba(var(--nc-primary-rgb), 0.22);
}
.qo-explainer__title { margin: 0 0 0.9rem; font-size: 1.02rem; font-weight: 700; }
.qo-explainer__grid { margin: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 19rem), 1fr)); gap: 0.9rem 1.4rem; }
.qo-explainer__item { min-width: 0; }
.qo-explainer__term { display: flex; align-items: center; gap: 0.45rem; font-weight: 650; font-size: 0.92rem; margin-bottom: 0.25rem; }
.qo-explainer__icon { font-size: 1rem; color: var(--nc-primary-bright, var(--nc-primary)); }
.qo-explainer__def { margin: 0; font-size: 0.87rem; line-height: 1.6; color: var(--nc-text-secondary, #9aa0a6); overflow-wrap: anywhere; }
.qo-explainer__code { display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.4rem; }
.qo-explainer__code code {
  font-family: 'JetBrains Mono', 'IBM Plex Mono', ui-monospace, Menlo, Consolas, monospace; font-size: 0.78rem;
  color: var(--nc-text-primary, #e8eaed); background: rgba(0, 0, 0, 0.3); border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 6px; padding: 0.15rem 0.45rem; overflow-wrap: anywhere;
}
.qo-fold-enter-active, .qo-fold-leave-active { transition: opacity 220ms ease, transform 220ms ease; }
.qo-fold-enter-from, .qo-fold-leave-to { opacity: 0; transform: translateY(-6px); }

/* ── panels ──────────────────────────────────────────────────────────────────────────────────────────────────────── */
.qo-panel {
  position: relative; border-radius: 18px; padding: 1.4rem 1.5rem 1.5rem;
  background: rgba(255, 255, 255, 0.025);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  box-shadow: 0 24px 60px -36px rgba(0, 0, 0, 0.9);
  display: flex; flex-direction: column; gap: 1rem;
}
.qo-panel::before {
  content: ''; position: absolute; left: 1.5rem; right: 1.5rem; top: -1px; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(var(--nc-primary-rgb), 0.55), transparent);
}
.qo-panel--issued { gap: 1.25rem; }
.qo-panel__head { display: flex; flex-direction: column; gap: 0.45rem; }
.qo-panel__title { margin: 0; font-size: 1.15rem; font-weight: 700; }
.qo-panel__sub { margin: 0; display: flex; align-items: flex-start; gap: 0.5rem; font-size: 0.88rem; line-height: 1.55; color: var(--nc-text-secondary, #9aa0a6); max-width: 70ch; }
.qo-panel__sub-icon { font-size: 1rem; margin-top: 0.15rem; color: var(--nc-primary-bright, var(--nc-primary)); }

/* ── the issue form ──────────────────────────────────────────────────────────────────────────────────────────────── */
.qo-issue { display: flex; flex-direction: column; gap: 0.85rem; }
.qo-field { display: flex; flex-direction: column; gap: 0.4rem; min-width: 0; }
.qo-label { font-size: 0.82rem; font-weight: 650; color: var(--nc-text-primary, #e8eaed); }
.qo-issue__row { display: flex; gap: 0.6rem; align-items: stretch; }
.qo-input {
  flex: 1 1 auto; min-width: 0; width: 100%; box-sizing: border-box;
  font: inherit; font-size: 16px; line-height: 1.4; padding: 0.75rem 0.95rem; border-radius: 12px;
  border: 1px solid var(--nc-border, #2a2f3e);
}
/* The global input rule (neural-command.css) paints every field's border in --nc-border with !important: 1.39:1 against
   this panel, under the 3:1 a control's outline needs. A scoped rule outranks it (one more class), focus included. */
.qo-input, .qo-search__input { border-color: rgba(255, 255, 255, 0.38) !important; }
.qo-input:focus, .qo-search__input:focus {
  border-color: var(--nc-primary) !important;
  box-shadow: 0 0 0 3px rgba(var(--nc-primary-rgb), 0.35) !important;
}
.qo-textarea { resize: vertical; min-height: 4.2rem; }
.qo-issue__go { flex: 0 0 auto; }
.qo-hint { margin: 0; font-size: 0.8rem; line-height: 1.55; }
.qo-hint__code {
  font-family: 'JetBrains Mono', 'IBM Plex Mono', ui-monospace, Menlo, Consolas, monospace; font-size: 0.78rem;
  color: var(--nc-text-primary, #e8eaed); background: rgba(0, 0, 0, 0.3); border-radius: 5px; padding: 0.05rem 0.4rem;
  overflow-wrap: anywhere;
}
.qo-field__msg { margin: 0; font-size: 0.82rem; color: #ffc1cd; }
.qo-disclose {
  align-self: flex-start; display: inline-flex; align-items: center; gap: 0.35rem; cursor: pointer;
  background: none; border: 0; padding: 0.2rem 0.1rem; font: inherit; font-size: 0.86rem; font-weight: 600;
  color: var(--nc-text-primary, #e8eaed);
}
.qo-disclose:hover { color: var(--nc-primary-bright, var(--nc-primary)); }
.qo-disclose:focus-visible { outline: 2px solid var(--nc-primary-bright, var(--nc-primary)); outline-offset: 2px; border-radius: 6px; }
.qo-disclose__chev { font-size: 1rem; transition: transform 180ms ease; }
.qo-disclose__chev.is-open { transform: rotate(90deg); }

/* ── notices and errors ──────────────────────────────────────────────────────────────────────────────────────────── */
.qo-notice { display: flex; gap: 0.75rem; align-items: flex-start; border-radius: 14px; padding: 0.9rem 1rem; }
.qo-notice--warn { background: var(--nc-warning-subtle); border: 1px solid var(--nc-warning-glow); }
.qo-notice__icon { font-size: 1.3rem; color: var(--nc-warning-bright); flex: 0 0 auto; margin-top: 0.1rem; }
.qo-notice__body { display: flex; flex-direction: column; gap: 0.4rem; min-width: 0; }
.qo-notice__title { margin: 0; font-weight: 700; color: #ffe6bd; }
.qo-notice__text { margin: 0; font-size: 0.88rem; line-height: 1.55; color: var(--nc-text-primary, #e8eaed); }
.qo-notice__actions { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-top: 0.2rem; }
.qo-notice__results { display: flex; flex-direction: column; gap: 0.25rem; }
.qo-notice__results:empty { display: none; }
.qo-notice__result { margin: 0; font-size: 0.82rem; color: var(--nc-text-secondary, #9aa0a6); }
.qo-error {
  display: flex; align-items: flex-start; gap: 0.5rem; margin: 0; padding: 0.7rem 0.85rem; border-radius: 12px;
  font-size: 0.88rem; line-height: 1.5; color: #ffc1cd;
  background: var(--nc-danger-subtle); border: 1px solid var(--nc-danger-glow);
}
.qo-error__icon { font-size: 1.05rem; flex: 0 0 auto; margin-top: 0.12rem; }

/* ── buttons and links ───────────────────────────────────────────────────────────────────────────────────────────── */
.qo-btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 0.45rem;
  min-height: 44px; padding: 0.55rem 1.1rem; border-radius: 12px; cursor: pointer; text-decoration: none;
  font: inherit; font-size: 0.9rem; font-weight: 650; line-height: 1.2; white-space: nowrap;
  transition: background var(--nc-duration-fast, 200ms) ease, border-color var(--nc-duration-fast, 200ms) ease,
    box-shadow var(--nc-duration-fast, 200ms) ease, transform 120ms ease;
}
.qo-btn:focus-visible { outline: 2px solid var(--nc-primary-bright, var(--nc-primary)); outline-offset: 2px; }
.qo-btn:disabled { opacity: 0.55; cursor: not-allowed; }
.qo-btn:active:not(:disabled) { transform: translateY(1px); }
.qo-btn__icon { font-size: 1.05rem; }
.qo-btn--primary {
  color: #ffffff; border: 1px solid rgba(var(--nc-primary-rgb), 0.75);
  background: linear-gradient(180deg, rgba(var(--nc-primary-rgb), 0.34), rgba(var(--nc-primary-rgb), 0.2));
  box-shadow: 0 10px 26px -14px rgba(var(--nc-primary-rgb), 0.85), inset 0 1px 0 rgba(255, 255, 255, 0.12);
}
.qo-btn--primary:hover:not(:disabled) {
  background: linear-gradient(180deg, rgba(var(--nc-primary-rgb), 0.46), rgba(var(--nc-primary-rgb), 0.28));
  box-shadow: 0 12px 30px -12px rgba(var(--nc-primary-rgb), 0.95), inset 0 1px 0 rgba(255, 255, 255, 0.16);
}
.qo-btn--ghost { color: var(--nc-text-primary, #e8eaed); background: transparent; border: 1px solid rgba(255, 255, 255, 0.16); }
.qo-btn--ghost:hover { border-color: rgba(var(--nc-primary-rgb), 0.55); background: rgba(var(--nc-primary-rgb), 0.06); }
.qo-btn--quiet {
  min-height: 36px; padding: 0.35rem 0.75rem; border-radius: 10px; font-size: 0.82rem;
  color: var(--nc-text-primary, #e8eaed); background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.12);
}
.qo-btn--quiet:hover:not(:disabled) { border-color: rgba(var(--nc-primary-rgb), 0.55); background: rgba(var(--nc-primary-rgb), 0.08); }
.qo-link {
  display: inline-flex; align-items: center; gap: 0.3rem; font-weight: 600; font-size: 0.86rem;
  color: var(--nc-primary-bright, var(--nc-primary)); text-decoration: underline; text-underline-offset: 3px;
}
.qo-link:hover { color: var(--nc-text-primary, #e8eaed); }
.qo-link:focus-visible { outline: 2px solid var(--nc-primary-bright, var(--nc-primary)); outline-offset: 2px; border-radius: 4px; }
.qo-link__icon { font-size: 0.9rem; }
.qo-spin { animation: qo-spin 0.9s linear infinite; }
@keyframes qo-spin { to { transform: rotate(360deg); } }

/* ── the issued identity: a card ─────────────────────────────────────────────────────────────────────────────────── */
.qo-idcard {
  position: relative; overflow: hidden; border-radius: 20px; padding: 0 0 1.25rem;
  background:
    repeating-radial-gradient(circle at 88% 12%, rgba(var(--nc-primary-rgb), 0.05) 0 1px, transparent 1px 9px),
    linear-gradient(155deg, rgba(var(--nc-primary-rgb), 0.16), rgba(var(--nc-primary-rgb), 0.03) 48%, transparent),
    var(--nc-deep);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.35);
  box-shadow: 0 28px 70px -30px rgba(var(--nc-primary-rgb), 0.45), inset 0 1px 0 rgba(255, 255, 255, 0.07);
  animation: qo-rise 420ms cubic-bezier(.2, .7, .3, 1) both;
}
.qo-idcard__sheen {
  position: absolute; inset: -40% -60%; pointer-events: none; z-index: 0;
  background: linear-gradient(110deg, transparent 44%, rgba(255, 255, 255, 0.07) 50%, transparent 56%);
  animation: qo-sheen 1.6s ease-out 0.2s both;
}
.qo-idcard > *:not(.qo-idcard__sheen) { position: relative; z-index: 1; }
.qo-idcard__band {
  display: flex; justify-content: space-between; align-items: baseline; gap: 0.5rem 1rem; flex-wrap: wrap;
  padding: 0.85rem 1.4rem; border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.22);
  background: linear-gradient(90deg, rgba(var(--nc-primary-rgb), 0.1), rgba(var(--nc-primary-rgb), 0.02));
}
.qo-idcard__eyebrow {
  display: inline-flex; align-items: center; gap: 0.5rem;
  font-size: 0.74rem; font-weight: 800; letter-spacing: 0.2em; text-transform: uppercase; color: var(--nc-text-primary, #e8eaed);
}
.qo-idcard__eyebrow::before {
  content: ''; width: 0.5rem; height: 0.5rem; border-radius: 50%; background: var(--nc-primary-bright, var(--nc-primary));
  box-shadow: 0 0 10px rgba(var(--nc-primary-rgb), 0.8);
}
.qo-idcard__issuer { font-size: 0.82rem; color: var(--nc-text-primary, #e8eaed); }
.qo-idcard__main { display: flex; gap: 1.2rem; padding: 1.2rem 1.4rem 0; align-items: flex-start; }
.qo-idcard__portrait {
  position: relative; flex: 0 0 auto; width: 5.5rem; height: 6.6rem; border-radius: 14px; display: grid; place-items: center;
  background: radial-gradient(circle at 50% 35%, rgba(var(--nc-primary-rgb), 0.3), rgba(var(--nc-primary-rgb), 0.05) 70%);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.45);
  box-shadow: inset 0 0 24px rgba(var(--nc-primary-rgb), 0.18);
}
.qo-idcard__glyph { font-size: 2.7rem; color: var(--nc-primary-bright, var(--nc-primary)); filter: drop-shadow(0 0 10px rgba(var(--nc-primary-rgb), 0.55)); }
.qo-idcard__initial {
  position: absolute; right: 0.4rem; bottom: 0.3rem; font-size: 0.85rem; font-weight: 800;
  color: var(--nc-text-primary, #e8eaed); opacity: 0.85;
}
.qo-idcard__facts { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; gap: 0.55rem; }
.qo-idcard__name { margin: 0; font-size: 1.45rem; font-weight: 750; letter-spacing: -0.01em; line-height: 1.2; overflow-wrap: anywhere; }
.qo-idcard__name:focus { outline: none; }
.qo-idcard__chips { margin: 0; display: flex; gap: 0.4rem; flex-wrap: wrap; }
.qo-idcard__chips:empty { display: none; }
.qo-idcard__field { display: flex; flex-direction: column; gap: 0.3rem; min-width: 0; }
.qo-idcard__label { font-size: 0.7rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--nc-text-secondary, #9aa0a6); }
.qo-idcard__value-line { display: flex; align-items: center; gap: 0.45rem; flex-wrap: wrap; min-width: 0; }
.qo-idcard__did {
  flex: 1 1 16rem; min-width: 0;
  font-family: 'JetBrains Mono', 'IBM Plex Mono', ui-monospace, Menlo, Consolas, monospace; font-size: 0.85rem; line-height: 1.45;
  color: var(--nc-text-primary, #e8eaed); overflow-wrap: anywhere;
  background: rgba(0, 0, 0, 0.32); border: 1px solid rgba(255, 255, 255, 0.07); border-radius: 8px; padding: 0.45rem 0.65rem;
}
.qo-idcard__creds { padding: 1.1rem 1.4rem 0; }
.qo-idcard__reset {
  display: flex; align-items: flex-start; gap: 0.5rem; margin: 0; padding: 0.7rem 0.85rem; border-radius: 12px;
  font-size: 0.86rem; line-height: 1.5; color: var(--nc-text-primary, #e8eaed);
  background: rgba(255, 255, 255, 0.04); border: 1px solid rgba(255, 255, 255, 0.12);
}
.qo-idcard__reset-icon { font-size: 1rem; flex: 0 0 auto; margin-top: 0.12rem; color: var(--nc-text-secondary, #9aa0a6); }
.qo-idcard__notes { list-style: none; margin: 0; padding: 0.9rem 1.4rem 0; display: flex; flex-direction: column; gap: 0.45rem; }
.qo-idcard__notes:empty { display: none; }
.qo-idcard__note { display: flex; align-items: flex-start; gap: 0.5rem; font-size: 0.86rem; line-height: 1.5; color: var(--nc-text-primary, #e8eaed); }
.qo-idcard__note[data-kind="credited"] .qo-idcard__note-icon { color: var(--nc-success); }
.qo-idcard__note[data-kind="partial"] .qo-idcard__note-icon,
.qo-idcard__note[data-kind="deferred"] .qo-idcard__note-icon { color: var(--nc-warning-bright); }
.qo-idcard__note[data-kind="failed"] .qo-idcard__note-icon { color: var(--nc-danger-bright); }
.qo-idcard__note-icon { font-size: 1rem; flex: 0 0 auto; margin-top: 0.12rem; color: var(--nc-text-secondary, #9aa0a6); }

/* ── the card and "use it" ───────────────────────────────────────────────────────────────────────────────────────── */
.qo-sub { display: flex; flex-direction: column; gap: 0.6rem; }
.qo-sub__head { display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; flex-wrap: wrap; }
.qo-sub__title { margin: 0; font-size: 1rem; font-weight: 700; display: inline-flex; align-items: baseline; gap: 0.5rem; }
.qo-sub__tag {
  font-size: 0.7rem; font-weight: 700; letter-spacing: 0.06em; padding: 0.12rem 0.45rem; border-radius: 6px;
  color: var(--nc-text-primary, #e8eaed); background: rgba(var(--nc-primary-rgb), 0.14); border: 1px solid rgba(var(--nc-primary-rgb), 0.35);
}
.qo-sub__actions { display: flex; align-items: center; gap: 0.6rem 1rem; flex-wrap: wrap; }
.qo-valid {
  display: inline-flex; align-items: center; gap: 0.35rem; font-size: 0.8rem; font-weight: 700;
  color: #b7ffd9; background: var(--nc-success-subtle); border: 1px solid var(--nc-success-glow);
  border-radius: 999px; padding: 0.22rem 0.65rem;
}
.qo-valid__icon { font-size: 0.95rem; }
.qo-json :deep(.jv-label), .qo-json :deep(.jv-btn) { color: var(--nc-text-primary, #e8eaed); }
.qo-json :deep(.jv-bytes), .qo-json :deep(.jv-collapsed) { color: var(--nc-text-secondary, #9aa0a6); }
.qo-snippet { display: flex; align-items: flex-start; gap: 0.5rem; min-width: 0; }
.qo-snippet__pre {
  flex: 1 1 auto; min-width: 0; margin: 0; overflow-x: auto;
  font-family: 'JetBrains Mono', 'IBM Plex Mono', ui-monospace, Menlo, Consolas, monospace; font-size: 0.8rem; line-height: 1.6;
  color: #d4dbe8; background: rgba(0, 0, 0, 0.38); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 12px;
  padding: 0.8rem 0.95rem; white-space: pre;
}
.qo-snippet__pre:focus-visible { outline: 2px solid var(--nc-primary-bright, var(--nc-primary)); outline-offset: 2px; }
.qo-result-actions { display: flex; gap: 0.6rem; flex-wrap: wrap; justify-content: flex-end; padding-top: 0.25rem; }

/* ── chips ───────────────────────────────────────────────────────────────────────────────────────────────────────── */
.qo-chip {
  display: inline-flex; align-items: center; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.02em;
  padding: 0.14rem 0.5rem; border-radius: 999px; white-space: nowrap;
  color: var(--nc-text-primary, #e8eaed); background: rgba(var(--nc-primary-rgb), 0.14); border: 1px solid rgba(var(--nc-primary-rgb), 0.4);
}
.qo-chip--warn { color: #ffe6bd; background: var(--nc-warning-subtle); border-color: var(--nc-warning-glow); }
.qo-chip--live { color: #c9ffe4; background: var(--nc-success-subtle); border-color: var(--nc-success-glow); }

/* ── your agents ─────────────────────────────────────────────────────────────────────────────────────────────────── */
.qo-agents { display: flex; flex-direction: column; gap: 0.85rem; padding-top: 0.5rem; }
.qo-agents__head { position: relative; display: flex; align-items: flex-end; justify-content: space-between; gap: 0.75rem 1rem; flex-wrap: wrap; }
.qo-agents__titles { display: flex; align-items: baseline; gap: 0.75rem; flex-wrap: wrap; }
.qo-agents__title { margin: 0; font-size: 1.2rem; font-weight: 700; }
.qo-agents__count { margin: 0; font-size: 0.85rem; color: var(--nc-text-secondary, #9aa0a6); }
.qo-agents__tools { display: flex; align-items: center; justify-content: flex-end; gap: 0.6rem; flex-wrap: wrap; flex: 1 1 28rem; max-width: 38rem; }
.qo-search { position: relative; display: flex; align-items: center; min-width: min(100%, 16rem); flex: 1 1 18rem; }
.qo-search__icon {
  position: absolute; left: 0.8rem; top: 50%; transform: translateY(-50%); pointer-events: none;
  font-size: 1.05rem; color: var(--nc-text-secondary, #9aa0a6);
}
.qo-search__input {
  width: 100%; min-width: 0; box-sizing: border-box; font: inherit; font-size: 16px; line-height: 1.4;
  min-height: 44px; padding: 0.55rem 0.8rem 0.55rem 2.35rem; border-radius: 12px; border: 1px solid var(--nc-border, #2a2f3e);
}
.qo-eye {
  display: inline-flex; align-items: center; gap: 0.45rem; min-height: 44px; padding: 0.45rem 0.9rem; border-radius: 12px; cursor: pointer;
  font: inherit; font-size: 0.86rem; font-weight: 650; color: var(--nc-text-primary, #e8eaed);
  background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.14);
  transition: background var(--nc-duration-fast, 200ms) ease, border-color var(--nc-duration-fast, 200ms) ease;
}
.qo-eye:hover { border-color: rgba(var(--nc-primary-rgb), 0.55); }
.qo-eye.is-on { background: rgba(var(--nc-primary-rgb), 0.12); border-color: rgba(var(--nc-primary-rgb), 0.55); }
.qo-eye:focus-visible { outline: 2px solid var(--nc-primary-bright, var(--nc-primary)); outline-offset: 2px; }
.qo-eye__icon { font-size: 1.1rem; }
.qo-slice { margin: 0; display: flex; align-items: center; gap: 0.45rem; font-size: 0.84rem; color: var(--nc-text-secondary, #9aa0a6); }
.qo-slice__icon { font-size: 1rem; flex: 0 0 auto; }
.qo-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.6rem; }
.qo-refresh {
  position: absolute; left: 0; right: 0; bottom: -0.5rem; height: 2px; overflow: hidden; border-radius: 2px;
  background: rgba(var(--nc-primary-rgb), 0.12);
}
.qo-refresh__bar {
  position: absolute; inset: 0; width: 40%;
  background: linear-gradient(90deg, transparent, rgba(var(--nc-primary-rgb), 0.75), transparent);
  animation: qo-refresh 1.1s ease-in-out infinite;
}
@keyframes qo-refresh { from { transform: translateX(-100%); } to { transform: translateX(250%); } }
.qo-row {
  display: grid; grid-template-columns: minmax(0, 1fr) auto; grid-template-areas: 'id actions' 'facts facts';
  align-items: center; gap: 0.8rem 1.25rem;
  padding: 0.95rem 1.1rem; border-radius: 14px;
  background: rgba(255, 255, 255, 0.022); border: 1px solid rgba(255, 255, 255, 0.07);
  transition: border-color var(--nc-duration-fast, 200ms) ease, background var(--nc-duration-fast, 200ms) ease;
}
.qo-row:hover { border-color: rgba(var(--nc-primary-rgb), 0.3); background: rgba(var(--nc-primary-rgb), 0.035); }
.qo-row--new { border-color: rgba(var(--nc-primary-rgb), 0.5); box-shadow: 0 0 0 3px rgba(var(--nc-primary-rgb), 0.08); }
.qo-row__id { grid-area: id; display: flex; align-items: center; gap: 0.75rem; min-width: 0; }
.qo-row__avatar {
  flex: 0 0 auto; width: 2.4rem; height: 2.4rem; border-radius: 12px; display: grid; place-items: center;
  font-weight: 800; font-size: 1rem; color: var(--nc-text-primary, #e8eaed);
  background: linear-gradient(160deg, rgba(var(--nc-primary-rgb), 0.3), rgba(var(--nc-primary-rgb), 0.08));
  border: 1px solid rgba(var(--nc-primary-rgb), 0.35);
}
.qo-row__names { display: flex; flex-direction: column; gap: 0.3rem; min-width: 0; }
.qo-row__name { font-weight: 700; font-size: 0.95rem; overflow-wrap: anywhere; }
.qo-row__chips { display: flex; gap: 0.3rem; flex-wrap: wrap; }
.qo-row__chips:empty { display: none; }
.qo-row__facts {
  grid-area: facts; margin: 0; display: flex; flex-wrap: wrap; align-items: flex-start;
  gap: 0.5rem 2.25rem; min-width: 0; padding-top: 0.7rem; border-top: 1px solid rgba(255, 255, 255, 0.06);
}
.qo-row__fact { min-width: 0; max-width: 100%; }
.qo-row__fact--id { min-width: 0; }
.qo-row__term { font-size: 0.68rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--nc-text-secondary, #9aa0a6); }
.qo-row__def { margin: 0.15rem 0 0; display: flex; align-items: center; gap: 0.3rem; font-size: 0.84rem; min-width: 0; }
.qo-row__code {
  font-family: 'JetBrains Mono', 'IBM Plex Mono', ui-monospace, Menlo, Consolas, monospace; font-size: 0.8rem;
  color: var(--nc-text-primary, #e8eaed); white-space: nowrap;
}
.qo-row__none { color: var(--nc-text-secondary, #9aa0a6); }
.qo-row__balance { font-variant-numeric: tabular-nums; }
.qo-row__actions { grid-area: actions; display: flex; align-items: center; justify-content: flex-end; gap: 0.45rem; flex-wrap: wrap; }
.qo-row__note { font-size: 0.8rem; color: #ffe6bd; }
.qo-mask { color: var(--nc-text-secondary, #9aa0a6); letter-spacing: 0.08em; white-space: nowrap; }
.qo-amount { font-weight: 650; color: var(--nc-text-primary, #e8eaed); white-space: nowrap; }
.qo-unread { display: inline-flex; flex-direction: column; gap: 0.1rem; min-width: 0; max-width: 18rem; }
.qo-unread__word { color: var(--nc-text-primary, #e8eaed); font-weight: 600; }
.qo-unread__why { font-size: 0.72rem; line-height: 1.4; color: var(--nc-text-secondary, #9aa0a6); overflow-wrap: anywhere; }
.qo-shimmer {
  display: inline-block; width: 4.5rem; height: 0.8rem; border-radius: 6px;
  background: linear-gradient(90deg, rgba(255, 255, 255, 0.05), rgba(255, 255, 255, 0.14), rgba(255, 255, 255, 0.05));
  background-size: 200% 100%; animation: qo-shimmer 1.2s ease-in-out infinite;
}
.qo-skeleton { display: flex; flex-direction: column; gap: 0.6rem; }
.qo-skeleton__row {
  height: 4.4rem; border-radius: 14px; border: 1px solid rgba(255, 255, 255, 0.06);
  background: linear-gradient(90deg, rgba(255, 255, 255, 0.02), rgba(255, 255, 255, 0.06), rgba(255, 255, 255, 0.02));
  background-size: 200% 100%; animation: qo-shimmer 1.4s ease-in-out infinite;
}
.qo-empty {
  display: flex; flex-direction: column; align-items: center; gap: 0.6rem; text-align: center;
  padding: 2rem 1rem; border-radius: 16px; border: 1px dashed rgba(var(--nc-primary-rgb), 0.3); background: rgba(var(--nc-primary-rgb), 0.03);
}
.qo-empty__icon { font-size: 2rem; color: var(--nc-primary-bright, var(--nc-primary)); }
.qo-empty__text { margin: 0; font-size: 0.92rem; color: var(--nc-text-primary, #e8eaed); }

@keyframes qo-rise { from { opacity: 0; transform: translateY(12px) scale(0.99); } to { opacity: 1; transform: none; } }
@keyframes qo-sheen { from { transform: translateX(-35%); opacity: 0; } 30% { opacity: 1; } to { transform: translateX(35%); opacity: 0; } }
@keyframes qo-shimmer { 0% { background-position: 100% 0; } 100% { background-position: -100% 0; } }

/* ── narrower screens ────────────────────────────────────────────────────────────────────────────────────────────── */
@media (max-width: 640px) {
  .qo-view { padding: 1.1rem 1rem 2.5rem; gap: 1rem; }
  .qo-hero { gap: 0.85rem; }
  .qo-hero__mark { width: 3rem; height: 3rem; border-radius: 15px; }
  .qo-hero__icon { font-size: 1.5rem; }
  .qo-panel { padding: 1.1rem 1rem 1.2rem; border-radius: 16px; }
  .qo-issue__row { flex-direction: column; }
  .qo-issue__go { width: 100%; }
  .qo-idcard__band, .qo-idcard__main, .qo-idcard__creds, .qo-idcard__notes { padding-left: 1rem; padding-right: 1rem; }
  .qo-idcard__main { flex-direction: column; }
  .qo-idcard__portrait { width: 4.4rem; height: 5.2rem; }
  .qo-idcard__glyph { font-size: 2.2rem; }
  .qo-result-actions { justify-content: stretch; }
  .qo-result-actions > * { flex: 1 1 100%; }
  .qo-agents__tools { width: 100%; }
  .qo-eye { flex: 1 1 auto; justify-content: center; }
  .qo-row { grid-template-columns: minmax(0, 1fr); grid-template-areas: 'id' 'facts' 'actions'; }
  .qo-row__facts { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 0.6rem 1rem; }
  /* the two identifiers each take the row's width on a phone; created and balance share a line */
  .qo-row__fact--id { grid-column: 1 / -1; }
  .qo-row__code { white-space: normal; overflow-wrap: anywhere; }
  /* a large balance in half a phone row: the currency takes the next line rather than the cell's edge */
  .qo-amount { white-space: normal; overflow-wrap: anywhere; }
  .qo-row__actions { justify-content: flex-start; }
}
@media (prefers-reduced-motion: reduce) {
  .qo-idcard, .qo-idcard__sheen, .qo-shimmer, .qo-skeleton__row, .qo-spin, .qo-refresh__bar { animation: none; }
  .qo-idcard__sheen { display: none; }
  .qo-refresh__bar { width: 100%; }
  .qo-fold-enter-active, .qo-fold-leave-active, .qo-disclose__chev, .qo-btn, .qo-row, .qo-eye, .qo-info { transition: none; }
}
</style>
