<template>
  <!-- §OURSTATE-1 — one thread. The composer is a command line (fill, never
       fire); every economic act is a typed card over an EXISTING rail; every
       name renders the WHOLE identity (the mandate). -->
  <div ref="rootEl" class="ost" :class="{ 'ost--desk': surface === 'desk', 'ost--narrow': narrowPane(paneWidth) }"
       data-testid="ost-root">
    <header class="ost-head">
      <!-- V0653 (al): beside the list (two panes) the arrow folds and opens the list and never leaves the thread; on a
           phone it leaves the thread for the list, as before -->
      <button class="ost-back" data-testid="ost-back" :data-act="arrowAct" :aria-label="arrowLabel" :title="arrowLabel"
              @click="onArrow"><Icon :name="arrowAct === 'open-list' ? 'mdi:chevron-right' : 'mdi:chevron-left'" /></button>
      <OurStateIdentity v-if="counterparty" class="ost-who" data-testid="ost-counterparty"
                        :ptype="identityKind(counterparty.ptype)"
                        :pid="identityPid(counterparty)"
                        :fallback-name="counterparty.name" size="sm" show-name
                        :clickable="counterparty.ptype === 'agent'"
                        @open="detailOpen = counterparty.ptype === 'agent'" />
      <span v-else-if="room" class="ost-who ost-room-head" data-testid="ost-room-head">
        <span class="ost-room-title">{{ room.title || t('ourstate.rooms.room', 'Org room') }}
          <span v-if="room.mode === 'announce'" class="ost-announce" data-testid="ost-room-announce">{{ t('ourstate.rooms.announce', 'announce') }}</span>
        </span>
        <span v-if="room.topic" class="ost-room-topic" data-testid="ost-room-topic">{{ room.topic }}</span>
      </span>
      <!-- §OURSTATE-7 D — a support thread names the desk, not a counterparty:
           there is no principal on the other side, only a rail. -->
      <span v-else-if="isSupportThread" class="ost-who ost-room-head" data-testid="ost-support-head">
        <span class="ost-room-title">{{ t('ourstate.support.desk', 'Support') }}</span>
        <span v-if="supportTicket?.subject" class="ost-room-topic">{{ supportTicket.subject }}</span>
      </span>
      <span v-else class="ost-who-loading">{{ err ? t('ourstate.thread.unavailable', 'Unavailable') : '…' }}</span>
      <!-- V0652 (ag): live, catching up or offline, by shape (a filled, half or hollow mark) and a word -->
      <span class="ost-live" :data-state="liveCatch.state.value" data-testid="ost-live"><i aria-hidden="true"></i>{{ liveWord }}</span>
      <!-- V0652 (ak): the settings button says what it is, on every surface (he could not find the bare dots) -->
      <button ref="menuBtn" type="button" class="ost-menu-btn ost-settings-btn" :class="{ open: menuOpen }" data-testid="ost-menu"
              :aria-label="t('ourstate.settings.button', 'Settings and actions for this conversation')"
              :title="t('ourstate.settings.button', 'Settings and actions for this conversation')"
              aria-haspopup="menu" :aria-expanded="menuOpen ? 'true' : 'false'"
              @click="menuOpen = !menuOpen"><Icon name="mdi:dots-horizontal" /><span class="ost-settings-word">{{ t('ourstate.settings.word', 'Settings') }}</span></button>
    </header>

    <!-- §OURSTATE-6 — the honest hosting line, and the timer if one is set.
         The E2EE spike's conclusion in one row: we do not claim the operator
         cannot read this, we say that they can and show how long it stays. -->
    <div class="ost-hosting" data-testid="ost-hosting" data-tour="ourchat-hosting">
      <Icon name="mdi:server" />
      <!-- §TWOAGENT V0441: a thread with another registry is held by its host AND copied to every other registry in
           it (the API names both); a mirror said "Hosted by <this registry>" about a thread hosted elsewhere. -->
      <span v-if="hosting?.copies?.length">{{ tp('ourstate.thread.hostedByCopies',
                  'Hosted by {reg}, copied to {copies} — the operator of each can read this thread.',
                  { reg: hosting.registry, copies: hosting.copies.join(', ') }) }}</span>
      <span v-else>{{ tp('ourstate.thread.hostedBy',
                  'Hosted by {reg} — the operator can read this thread.',
                  { reg: hosting?.registry || t('pocket.send.thisRegistry', 'this registry') }) }}</span>
      <span v-if="retentionLabel" class="ost-hosting-timer" data-testid="ost-hosting-timer">
        · {{ retentionLabel }}</span>
    </div>

    <!-- §OCOPTIN — the visibility law's second half: while the org has opted
         into public transparency, its members SEE that the room's work records
         are public. Server-derived per open (live), never cached client-side. -->
    <div v-if="room?.transparency_public" class="ost-transparency" data-testid="ost-transparency">
      <Icon name="mdi:earth" />
      <span>{{ t('ourstate.room.transparencyBanner', "This room's work records are public — receipts, system rows and the topic serve on a read-only feed. Written messages stay private.") }}</span>
    </div>

    <!-- §ROOMBRAIN — presence is never silent: while an org admin keeps the
         assistant added, every member sees it and what it is allowed to read.
         Server-derived per open (live), like the transparency banner above. -->
    <div v-if="room?.assistant_present" class="ost-transparency ost-assistant" data-testid="ost-assistant-banner">
      <Icon name="mdi:robot-outline" />
      <span>{{ t('ourstate.room.assistantBanner', "@assistant is in this room — address it to read org records (receipts, the roster, the treasury). It reads nothing else and never volunteers.") }}</span>
    </div>

    <!-- §OURSTATE-7 D — the ticket's own state, read from the ticket. It says
         WHERE the decision lives, because the thread does not make it: a status
         a chat surface could change would be a second authority. -->
    <div v-if="isSupportThread" class="ost-support-bar" data-testid="ost-support-bar">
      <Icon name="mdi:lifebuoy" />
      <template v-if="supportTicket">
        <span data-testid="ost-support-status">{{ tp('ourstate.support.bar',
          'Ticket #{id} — {status}', { id: String(supportTicket.ticket_id),
                                       status: supportStatusWord(supportTicket.status) }) }}</span>
        <span class="ost-support-note">{{ t('ourstate.support.decides',
          'Support sets the status; replying here reopens a closed ticket.') }}</span>
      </template>
      <span v-else-if="supportErr" class="ost-support-err" data-testid="ost-support-err">{{ supportErr }}</span>
      <span v-else class="ost-support-note">{{ t('common.loading', 'Loading…') }}</span>
    </div>

    <!-- §CHATDESK C4 — the CONSENT BANNER: while any live grant exists, every
         participant sees that the desk can read this thread. Never covert. -->
    <ReadFailedNotice v-if="!isSupportThread && reviewUnknown && !liveReviewGrants.length" dense :retry="loadReviewBanner"
                      :text="t('cdr.bannerUnread', 'Whether support can review this conversation could not be checked just now.')"
                      data-testid="cd-review-unread" />
    <div v-if="!isSupportThread && liveReviewGrants.length" class="ost-review-banner" data-testid="cd-review-banner">
      <Icon name="mdi:eye-check-outline" />
      <span>{{ tp('cdr.banner', 'Support can review this conversation (ticket #{id}, allowed by {who}) — read-only, until the ticket closes.',
                  { id: String(liveReviewGrants[0].ticket_id), who: liveReviewGrants[0].granted_by_name || '?' }) }}</span>
      <button v-for="g in myRevocableGrants" :key="g.grant_id" class="ost-review-revoke"
              data-testid="cd-review-revoke" @click="revokeReview(g)">
        {{ t('cdr.revoke', 'Withdraw') }}</button>
    </div>

    <!-- §CHATDESK C4 — the FILER's grant flow, on the ticket's own thread:
         "let support look at one specific conversation". -->
    <details v-if="isSupportThread && supportTicket && ['open','in_progress'].includes(String(supportTicket.status))"
             class="ost-review-attach" data-testid="cd-review-attach" @toggle="loadAttachChoices">
      <summary>{{ t('cdr.attachTitle', 'Let support review one of your conversations') }}</summary>
      <p class="ost-review-note">{{ t('cdr.attachLede', 'Read-only, visible to everyone in that conversation as a system row, revocable, and it ends when this ticket closes. Org rooms can only be shared by an org owner or admin.') }}</p>
      <div class="ost-review-row">
        <select v-model="attachPick" class="ost-review-select" data-testid="cd-review-pick">
          <option value="" disabled>{{ t('cdr.attachPick', 'Pick a conversation…') }}</option>
          <option v-for="c in attachChoices" :key="c.id" :value="c.id">{{ c.title || c.kind + ' · ' + c.id.slice(0, 8) }}</option>
        </select>
        <button class="ost-review-grant" :disabled="!attachPick || attachBusy" data-testid="cd-review-grant"
                @click="grantReview">{{ t('cdr.grant', 'Allow review') }}</button>
      </div>
      <ReadFailedNotice v-if="attachFailed" dense :retry="loadAttachChoices"
                        :text="t('cdr.attachUnread', 'Your conversations could not be read just now.')"
                        data-testid="cd-review-pick-unread" />
      <p v-if="attachMsg" class="ost-review-msg" data-testid="cd-review-msg">{{ attachMsg }}</p>
    </details>

    <!-- V0652 (ak): the thread's settings, one menu for the console's #/ourchat, Pocket wide and the phone: a menu
         under the button on a wide screen, a sheet on a phone (ChatSettingsMenu). Each row hands its act back here. -->
    <ChatSettingsMenu v-if="menuOpen" :surface="wideMenu ? 'popover' : 'sheet'" :kind="settingsKind" :title="settingsTitle"
                      :subline="settingsSubline" :anchor="menuBtn" :room="settingsRoom" :retention="timerWord"
                      :timer-editable="timerEditable" :notify="notifyWord" :muted="mutedNow" :readers="readersLine"
                      :away="settingsAway" :can-block="canBlock" :counterparty-name="counterpartyName"
                      :ticket="settingsTicket" @close="closeMenu" @pick="onSettingsPick" />

    <!-- Room Genesis (§OURSTATE-2): the un-burnable wall. Two registers, split
         honestly — what the room STATES about itself vs what this registry
         actually ENFORCES here. Conversation state, not a message: burn-for-me
         structurally cannot hide it. -->
    <div v-if="room && room.genesis?.stated" class="ost-genesis" data-testid="ost-genesis">
      <button class="ost-genesis-head" @click="genesisOpen = !genesisOpen">
        <Icon name="mdi:script-text" />
        <span class="ost-genesis-line" :class="{ clamp: !genesisOpen }">{{ room.genesis.stated }}</span>
        <Icon :name="genesisOpen ? 'mdi:chevron-up' : 'mdi:chevron-down'" />
      </button>
      <div v-if="genesisOpen" class="ost-genesis-body">
        <p class="ost-genesis-reg">{{ t('ourstate.rooms.stated', 'Stated by the room — a promise, not a mechanism.') }}</p>
        <p class="ost-genesis-reg ost-genesis-enf" data-testid="ost-genesis-enforced">
          {{ t('ourstate.rooms.enforced', 'Enforced by the registry:') }}
          {{ room.mode === 'announce'
            ? t('ourstate.rooms.enfAnnounce', 'announce-only (org owners and admins post), operator mutes, membership from the org roster.')
            : t('ourstate.rooms.enfOpen', 'open posting, operator mutes, membership from the org roster.') }}
        </p>
        <p v-if="room.genesis.updated_by_name" class="ost-genesis-meta">
          {{ tp('ourstate.rooms.genesisBy', 'Last set by {who}', { who: room.genesis.updated_by_name }) }}</p>
      </div>
    </div>

    <!-- Request banner: cards below render DEFANGED until you accept (§6). -->
    <div v-if="myState === 'pending'" class="ost-request" data-testid="ost-request-banner">
      <p>{{ t('ourstate.thread.requestLine', 'This is a request from a stranger. Cards are defused until you accept.') }}</p>
      <div class="ost-req-btns">
        <button class="ost-btn ost-accept" data-testid="ost-accept" @click="acceptThread">{{ t('ourstate.list.accept', 'Accept') }}</button>
        <button class="ost-btn" @click="declineThread">{{ t('ourstate.list.decline', 'Decline') }}</button>
      </div>
    </div>

    <!-- Push opt-in (D3): never silent-on — one tap, and it names what it does. -->
    <div v-if="showPushCard" class="ost-pushcard" data-testid="ost-push-card">
      <Icon name="mdi:bell" />
      <span>{{ t('ourstate.thread.pushAskNeeds', 'Get a push on this device when you are named, written to directly or asked to decide? Off until you say so.') }}</span>
      <button class="ost-btn ost-accept" data-testid="ost-push-enable" :disabled="pushBusy" @click="enablePush">
        {{ pushBusy ? '…' : t('ourstate.thread.pushEnable', 'Enable') }}</button>
      <button class="ost-push-dismiss" :aria-label="t('common.close', 'Close')" @click="dismissPushCard"><Icon name="mdi:close" /></button>
    </div>
    <p v-if="pushMsg" class="ost-pushmsg">{{ pushMsg }}</p>

    <!-- §CHATPOLISH (2026-08-30) — `load()` has set `err` since §OURSTATE-1 and
         the template never read it. Measured: opening a thread you may not read
         (403) painted a room with the header stuck on its "…" placeholder, an
         empty body, and a LIVE composer — no error anywhere on screen. The
         sibling LIST view has always rendered its `err` in exactly this shape
         (PocketOurState.vue), so this is the missing half of a pattern that
         already exists, not a new one. Back is offered beside Retry because the
         common cause is access that has ended, which no retry will fix. -->
    <div v-if="err" class="ost-loaderr" data-testid="ost-loaderr">
      <Icon name="mdi:alert-circle" />
      <div class="ost-loaderr-body">
        <span class="ost-loaderr-title">{{ t('ourstate.thread.loadFailed', 'This conversation could not be opened.') }}</span>
        <span class="ost-loaderr-why">{{ err }}</span>
      </div>
      <button class="ost-loaderr-btn" data-testid="ost-loaderr-retry" @click="load()">{{ t('common.retry', 'Retry') }}</button>
      <button class="ost-loaderr-btn" data-testid="ost-loaderr-back" @click="router.push(base)">{{ t('common.back', 'Back') }}</button>
    </div>

    <!-- V0652 (ad): the column (approvals, history, composer) and, on the console's chat in an organization's room
         with a pane wide enough, the room's side panel beside it. Under that width the column is the whole thread. -->
    <div class="ost-body">
    <div class="ost-col">
    <!-- V0650 (l) — approvals pinned ABOVE the history: outside the scroll, so the messages move underneath and the
         requests stay put (his words: "it should stay locked above the chat window"). Org rooms only; decisions go
         with the developer token, never the speaking agent's.
         V0653 (al), his seq 686 ("the pinned version was way more clear to spot"): pinned at every width again, the
         side panel beside or not, and compact: one card with "n more", the one-line strip on a phone-width pane. -->
    <OurChatApprovals v-if="kind === 'org'" ref="approvalsPanel" compact :narrow="narrowPane(paneWidth)"
                      :conversation-id="convId" :token="token" :focus-id="focusApprovalId"
                      @count="approvalsCount = $event" @late="onApprovalsLate" />
    <!-- V0652 (ac): the room's status board, pinned beside the approvals (in the side panel when it shows) -->
    <ChatBoard v-if="kind === 'org' && room && !sideOn && (room.board?.text || room.board?.can_edit)" strip
               :board="room.board || null" :token="token" :conversation-id="convId" :org-id="String(room.org_id || '')"
               :viewer-key="myKey || 'me'" @update="onBoardUpdate" />

    <div ref="scrollEl" class="ost-scroll" data-testid="ost-messages">
      <ReadFailedNotice v-if="olderFailed" dense :retry="loadOlder"
                        :text="t('ourstate.thread.olderFailed', 'Older messages could not be read just now.')"
                        data-testid="ost-older-unread" />
      <button v-else-if="hasOlder" class="ost-older" @click="loadOlder">{{ t('ourstate.thread.older', 'Load older') }}</button>
      <!-- V0652 (x): what names you or waits on you, on its own (the rest of the room one tap away) -->
      <button v-if="forMeCount" type="button" class="ost-forme-toggle" :class="{ on: forMeOnly }"
              data-testid="ost-forme-toggle" @click="forMeOnly = !forMeOnly">
        {{ forMeOnly ? t('ourstate.thread.forMeAll', 'Show the whole room')
          : tp('ourstate.thread.forMeOnly', 'For me ({n})', { n: forMeCount }) }}</button>
      <template v-for="(m, i) in shownMessages" :key="m.id">
        <div v-if="unreadLineId === m.id" class="ost-unread" data-testid="ost-unread-line">
          <span>{{ tp('ourstate.thread.newLine', 'NEW · {n}', { n: unreadCount }) }}</span></div>
        <!-- Immutable provenance: every speaker CHANGE re-shows the full
             identity (the mandate: avatar + encirclement + collar). -->
        <div v-if="speakerChanged(i)" class="ost-author" :class="{ mine: isMine(m) }"
             :data-testid="`ost-author-${m.seq}`">
          <!-- §DEALTHREADS — a SYSTEM sender is a rail, not a person: label it
               as one instead of dressing it as a developer ("dev deal-rail"). -->
          <span v-if="m.sender_ptype === 'system'" class="ost-rail-author" data-testid="ost-rail-author">
            <Icon name="mdi:cog" /> {{ railLabel(m.sender_id) }}
          </span>
          <OurStateIdentity v-else :ptype="identityKind(m.sender_ptype)"
                            :pid="m.sender_id" :fallback-name="m.sender_name || ''"
                            size="xs" show-name />
          <!-- V0652 (aj): an agent's message its owner sent through their own session (the registry verified it) -->
          <span v-if="m.sender_ptype === 'agent' && m.sent_by_owner" class="ost-by-owner" data-testid="ost-by-owner">
            {{ t('ourstate.thread.sentByOwner', 'sent by its owner') }}</span>
        </div>
        <div class="ost-msg" :class="{ mine: isMine(m), sys: m.kind === 'system', 'for-me': forMe(m), ask: isAsk(m),
                                       'in-thread': inThread.has(m.id) }"
             :data-testid="`ost-msg-${m.seq}`">
          <div v-if="m.deleted" class="ost-tombstone">{{ t('ourstate.thread.deleted', 'message deleted') }}</div>
          <div v-else-if="m.kind === 'system' && m.body === 'ping'" class="ost-ping-row" data-testid="ost-ping-row">
            <Icon name="mdi:bell" /> {{ tp('ourstate.thread.pinged', '{who} pinged', { who: m.sender_name || '' }) }}</div>
          <div v-else-if="m.kind === 'system' && String(m.body || '').startsWith('room.')"
               class="ost-sys-row" :data-testid="`ost-sysrow-${m.seq}`">
            <Icon name="mdi:gavel" /> {{ roomRowText(m) }}</div>
          <!-- §OURSTATE-6 — a timer change is a SENTENCE, not a machine string.
               It shipped rendering its own body verbatim ("retention.24h"), so
               the one row whose whole job is telling both sides what changed was
               the one row nobody could read. The `room.*` rows two lines up had
               a renderer; this one did not. Same class as an unbundled i18n key:
               the mechanism worked and the human got a token. -->
          <div v-else-if="m.kind === 'system' && String(m.body || '').startsWith('retention.')"
               class="ost-sys-row" :data-testid="`ost-sysrow-${m.seq}`">
            <Icon name="mdi:timer-sand" /> {{ retentionRowText(m) }}</div>
          <!-- §OURSTATE-7 D — a status change is a sentence for the same reason
               a timer change is: `support.resolved` is a machine string. -->
          <div v-else-if="m.kind === 'system' && String(m.body || '').startsWith('support.')"
               class="ost-sys-row" :data-testid="`ost-sysrow-${m.seq}`">
            <Icon name="mdi:lifebuoy" /> {{ supportRowText(m) }}</div>
          <OurStateCard v-else-if="m.kind === 'card'" :card="m.card" :defang="myState === 'pending'"
                        :live-settlement="liveSettle[m.card?.refs?.token_id] || null"
                        :live-approval="liveApproval[m.card?.data?.approval_id] || null"
                        :mine="isMine(m)" @pay="openPayDoor" @open-agent="openAgentDetail"
                        @open-work="openWorkDoor" @applet-door="openAppletDoor"
                        @open-trade="openTradeDoor"
                        @use-terms="p => openEngageConfirm(p)"
                        @counter-terms="p => openPropose(p, String(m.id || ''))"
                        @open-contract="p => openWorkDoor({ kind: 'contract.offer', ref: p.contractId })"
                        @accept-offer="acceptDealOffer"
                        @ask-back="askBack"
                        :rev="Number(m.card_rev) || 0" :updated-at="m.card_updated_at || null"
                        @history="openCardHistory(m)" />
          <div v-else-if="isMeAction(m)" class="ost-me-row">{{ m.sender_name }} {{ m.body.slice(4) }}</div>
          <!-- V0652 (x): markdown, chips, mentions, ids small and grey, a long message folded (ChatMessageBody) -->
          <ChatMessageBody v-else class="ost-bubble ost-md" :body="String(m.body || '')" :mentions="m.mentions"
                           :my-key="myKey" :my-names="myNames" />
          <!-- V0652 (x): a time on every message: the local time today, the date before it, the full time on hover/tap -->
          <time v-if="m.created_at && m.kind !== 'system'" class="ost-time" :datetime="m.created_at"
                :title="timeTitle(m.created_at, appLocale())" :data-testid="`ost-time-${m.seq}`"
                @click="toggleFullTime(m.id)">{{ fullTimeId === m.id ? timeTitle(m.created_at, appLocale())
                  : timeLabel(m.created_at, Date.now(), appLocale()) }}</time>
          <!-- V0653 (al), his seq 665 (a 6:37 among 9 pm): a thread drawn at its latest reply says when that reply came -->
          <span v-if="m.created_at && m.kind !== 'system' && lastReplyAt(m, bars[m.id])" class="ost-time ost-time-last"
                :data-testid="`ost-time-last-${m.seq}`"><span class="sr-only">, </span>{{ tp('ourstate.thread.lastReplyAt',
                  'last reply {time}', { time: timeLabel(String(lastReplyAt(m, bars[m.id])), Date.now(), appLocale()) }) }}</span>
          <!-- V0653 (w): a line sent with an API key (an MCP connector, the bridge, a script) says so: it is not a hand -->
          <span v-if="m.sent_with === 'api_key' && !m.deleted" class="ost-by-key" :data-testid="`ost-by-key-${m.seq}`"
                :title="t('ourstate.thread.sentWithKeyTitle', 'Sent with an API key (a connector, a bridge or a script), not typed in a signed-in console or Pocket')">
            {{ t('ourstate.thread.sentWithKey', 'sent with a key') }}</span>
          <!-- V0654 (ap): a line its owner's assistant wrote, posted by the registry at the owner's request: not a hand -->
          <span v-if="m.sent_with === 'assistant' && !m.deleted" class="ost-by-key ost-by-assistant"
                :data-testid="`ost-by-assistant-${m.seq}`"
                :title="t('ourstate.thread.byAssistantTitle', 'Written by the owner’s personal assistant and posted by the registry at the owner’s request, not typed by hand')">
            <Icon name="mdi:creation" class="ost-by-assistant-mark" />{{ isMine(m)
              ? t('ourstate.thread.byYourAssistant', 'written by your assistant')
              : t('ourstate.thread.byAssistant', 'written by the assistant') }}</span>
          <!-- V0652 (ac): answer this message; the reply folds under it -->
          <button v-if="canReplyTo(m)" type="button" class="ost-reply-btn" :data-testid="`ost-reply-${m.seq}`"
                  :aria-label="t('ourstate.thread.replyTo', 'Reply to this message')" @click="startReply(m)">
            {{ t('ourstate.thread.reply', 'Reply') }}</button>
        </div>
        <!-- V0652 (ac): a thread's bar under its root: how many it holds, what is new, what is for you, the latest -->
        <button v-if="bars[m.id]" type="button" class="ost-thread-bar" :class="{ open: bars[m.id].expanded, mine: isMine(m) }"
                :aria-expanded="bars[m.id].expanded ? 'true' : 'false'" :data-testid="`ost-thread-${m.seq}`"
                @click="toggleThread(bars[m.id])">
          <!-- V0653: the parts are apart in the text run too (session-lead, seq 685: a screen reader heard "1 newlast:"),
               each after the first led by a comma the eye does not need (the gap draws them apart) -->
          <span class="ost-thread-count">{{ threadWord(bars[m.id]) }}</span>
          <span v-if="bars[m.id].unread" class="ost-thread-new"><span class="sr-only">, </span>{{ tp('ourstate.thread.threadNew', '{n} new', { n: bars[m.id].unread }) }}</span>
          <span v-if="bars[m.id].forMe" class="ost-thread-forme"><span class="sr-only">, </span>{{ tp('ourstate.thread.threadForMe', '{n} for you', { n: bars[m.id].forMe }) }}</span>
          <span v-if="bars[m.id].last" class="ost-thread-last"><span class="sr-only">, </span>{{ tp('ourstate.thread.threadLast', 'last: {who}, {when}', {
            who: speakerName(bars[m.id].last), when: bars[m.id].last?.created_at ? timeLabel(String(bars[m.id].last?.created_at), Date.now(), appLocale()) : '' }) }}</span>
          <span class="ost-thread-act"><span class="sr-only">, </span>{{ bars[m.id].expanded ? t('ourstate.thread.threadHide', 'Hide') : t('ourstate.thread.threadShow', 'Show') }}</span>
        </button>
        <!-- V0654 (ap): what you asked your assistant after this line: only you see it, and its answer comes below -->
        <ChatAssistAsk v-for="a in asksAfter(m.seq)" :key="a.ref" :ask="a"
                       @retry="retryAsk" @edit="editAsk" @dismiss="dismissAsk" />
      </template>
      <ChatAssistAsk v-for="a in asksUnanchored" :key="a.ref" :ask="a"
                     @retry="retryAsk" @edit="editAsk" @dismiss="dismissAsk" />
      <div v-if="serviceBusy || serviceInflight" class="ost-calling" data-testid="ost-calling">
        <Icon name="mdi:refresh" class="pk-ptr-spin" /> {{ t('ourstate.thread.calling', 'Calling — one call at a time in this thread.') }}</div>
    </div>

    <!-- §TWOAGENT G1 (V0437): an owner's first open of its agent's cross-registry thread is a VISIBLE join -->
    <div v-if="joinPrompt" class="ost-joingate" data-testid="ost-join-gate">
      <p class="ost-joingate-title">{{ t('ourstate.thread.joinTitle', 'Join this thread?') }}</p>
      <p class="ost-joingate-body">{{ joinPrompt }}</p>
      <div class="ost-req-btns">
        <button type="button" class="ost-btn ost-accept ost-joingate-yes" data-testid="ost-join-yes" @click="confirmJoin">
          {{ t('ourstate.thread.joinConfirm', 'Join the thread') }}</button>
        <button type="button" class="ost-btn ost-joingate-no" data-testid="ost-join-no" @click="router.push(base)">
          {{ t('ourstate.thread.joinCancel', 'Not now') }}</button>
      </div>
    </div>
    <!-- Room speech gate: a blocked composer SAYS WHY (muted / announce-only) -->
    <div v-if="room && !roomComposer.canPost" class="ost-roomgate" data-testid="ost-room-gate">
      <Icon name="mdi:lock" />
      {{ t('ourstate.rooms.gate.' + roomComposer.noteKey, roomComposer.note) }}
    </div>

    <!-- Composer -->
    <footer v-if="!err && (!room || roomComposer.canPost)" class="ost-composer" data-tour="ourchat-composer">
      <div class="ost-input-wrap">
        <!-- V0652 (ac): the message this one answers (it folds under it) -->
        <div v-if="replyTo" class="ost-replying" data-testid="ost-replying">
          <span class="ost-replying-tx">{{ tp('ourstate.thread.replyingTo', 'Replying to {who}: {what}', { who: replyTo.who, what: replyTo.what }) }}</span>
          <button type="button" class="ost-replying-x" data-testid="ost-replying-cancel" :aria-label="t('ourstate.thread.replyCancel', 'Not a reply')"
                  @click="replyTo = null"><Icon name="mdi:close" /></button>
        </div>
        <div v-if="hint" class="ost-hint" data-testid="ost-hint">{{ hint }}
          <button v-if="hintSendAsText" class="ost-hint-send" @click="sendPlainAnyway">{{ t('ourstate.thread.sendAsText', 'send as text') }}</button>
          <button v-if="hintNeedsAgent" type="button" class="ost-hint-send" data-testid="ost-hint-create" @click="uiStore.openQuickAgentModal()">{{ t('ourstate.thread.createAgent', 'create your wallet agent') }}</button>
        </div>
        <div v-if="completionsList.length" class="ost-complete" data-testid="ost-complete">
          <button v-for="c in completionsList" :key="c.cmd" class="ost-complete-row" @click="input = c.cmd + ' '">
            <span class="ost-complete-cmd">{{ c.usage }}</span>
            <span class="ost-complete-gloss">{{ t(c.glossKey, c.glossFallback) }}</span>
          </button>
        </div>

        <!-- §OURSTATE-7 C — NAME completion for /card and /find. Identity
             renders in full here, exactly as it does on Discover and in the
             find sheet (the Commander's identity mandate): the same avatar,
             flare and rank collar, from the same discover rail. -->
        <div v-if="argHint" class="ost-complete ost-suggest" data-testid="ost-agent-suggest">
          <p v-if="agentSuggestBusy" class="ost-suggest-note">{{ t('common.loading', 'Loading…') }}</p>
          <p v-else-if="agentSuggestErr" class="ost-suggest-note ost-suggest-err"
             data-testid="ost-suggest-err">{{ agentSuggestErr }}</p>
          <p v-else-if="!agentSuggest.length" class="ost-suggest-note" data-testid="ost-suggest-none">
            {{ argHint.query
               ? tp('ourstate.card.noMatch', 'No agent matches “{q}”.', { q: argHint.query })
               : t('ourstate.card.typeToSearch', 'Type a name to search agents.') }}</p>
          <button v-for="a in agentSuggest" :key="a.did" class="ost-suggest-row"
                  :data-testid="`ost-suggest-${a.did}`" :disabled="sending"
                  @click="argHint.cmd === '/card'
                            ? shareAgentCard(a.did, a.name)
                            : (input = `/find ${a.name}`)">
            <UserAvatar :user="a" :avatar-url="a.card_data?.iconUrl || null" :display-name="a.name"
                        :track-record="a.track_record || null" size="sm" />
            <span class="ost-suggest-body">
              <span class="ost-suggest-name">{{ a.name }}</span>
              <span class="ost-suggest-price">{{ suggestPrice(a) }}</span>
            </span>
            <Icon :name="argHint.cmd === '/card' ? 'mdi:card-account-details' : 'mdi:magnify'"
                  class="ost-suggest-go" />
          </button>
        </div>
        <textarea ref="inputEl" v-model="input" class="ost-input" rows="1" data-testid="ost-input"
                  :placeholder="composerPlaceholder"
                  @keydown.enter.exact.prevent="send" />
      </div>
      <!-- The speaker chip: who says the next message, beside the button that sends it (V0652 (aj): it is always
           shown, and it says "you" unless an agent was chosen for this thread). Tap = choose who speaks here. -->
      <!-- V0654 (ap): amber, with the assistant's mark, while the assistant writes for this identity here -->
      <button class="ost-speaker" :class="{ assist: assistOn }" data-testid="ost-speaker" data-tour="ourchat-speaker"
              :title="assistOn ? tp('ourstate.assist.chipTitle', 'Your assistant writes as {who}: what you type goes to it, not to the room', { who: assistWhoName }) : speakerTitle"
              :data-speaker="speakerDid ? 'agent' : 'you'" :data-assist="assistOn ? 'on' : 'off'" @click="onSpeakerTap">
        <Icon :name="speakerIsAgent ? 'mdi:robot' : 'mdi:account'" />
        <Icon v-if="assistOn" name="mdi:creation" class="ost-speaker-assist" data-testid="ost-speaker-assist" />
        <span class="ost-speaker-as">{{ t('ourstate.thread.speakerAs', 'as') }}</span>
        <span class="ost-speaker-name">{{ speakerLabel }}</span>
      </button>
      <button class="ost-send" data-testid="ost-send" :disabled="sendDisabled"
              :aria-label="assistOn ? tp('ourstate.assist.sendAs', 'Ask your assistant to write as {who}', { who: assistWhoName })
                : tp('ourstate.thread.sendAs', 'Send as {who}', { who: speakerLabel })"
              @click="send"><Icon name="mdi:send" /></button>
    </footer>
    </div><!-- .ost-col -->
    <ChatSidePanel v-if="sideOn" :org-id="String(room?.org_id || '')" :viewer-key="myKey || 'me'"
                   :approvals-count="approvalsCount" :focus-approvals="!!focusApprovalId"
                   :wake-modes="room?.wake_modes || null" :can-set-wake="!!room?.can_set_wake" :wake-busy="wakeBusy"
                   @set-wake="(key, m) => setWake(key, m)">
      <!-- V0653 (al): WAITING ON YOU keeps its count; the requests themselves are pinned above the history, and this
           section opens their whole list there -->
      <template #approvals>
        <p v-if="approvalsCount === 0" class="ost-side-note" data-testid="oca-none">
          {{ t('ourstate.approvals.none', 'Nothing waits for a decision in this room.') }}</p>
        <template v-else-if="approvalsCount">
          <p class="ost-side-note" data-testid="ost-side-approvals-pinned">
            {{ tp('ourstate.side.approvalsPinned', '{n} pinned above the chat', { n: approvalsCount }) }}</p>
          <button type="button" class="ost-side-link" data-testid="ost-side-approvals-open" @click="approvalsPanel?.openList()">
            {{ t('ourstate.side.approvalsOpen', 'Show them all there') }}</button>
        </template>
      </template>
      <template #board>
        <ChatBoard :board="room?.board || null" :token="token" :conversation-id="convId" :org-id="String(room?.org_id || '')"
                   :viewer-key="myKey || 'me'" @update="onBoardUpdate" />
      </template>
    </ChatSidePanel>
    </div><!-- .ost-body -->

    <!-- Service-call confirm: the money moment. ActingContextNotice above the
         confirm; the quote is what the agent's own gate will accept. -->
    <div v-if="callConfirm" class="ost-sheet-veil" @click.self="callConfirm = null">
      <div ref="callSheetEl" class="ost-sheet" role="dialog" :aria-label="t('ourstate.thread.confirmCall', 'Confirm service call')" data-testid="ost-call-confirm">
        <ActingContextNotice strong />
        <h3>{{ t('ourstate.thread.confirmCall', 'Confirm service call') }}</h3>
        <p class="ost-sheet-ask">{{ callConfirm.ask }}</p>
        <p v-if="callConfirm.quote?.payment_required" class="ost-sheet-price" data-testid="ost-quote-line">
          {{ tp('ourstate.thread.quoteLine', 'Costs about {amt} {ccy} (card price {price} {pccy})', {
            amt: callConfirm.quote.recommended_amount || callConfirm.quote.your_amount || '?',
            ccy: actingCurrencyLabel,
            price: callConfirm.quote.price || '?', pccy: callConfirm.quote.price_currency || '' }) }}
        </p>
        <p v-else class="ost-sheet-price">{{ t('ourstate.thread.freeQuote', 'Free call — nothing will be charged.') }}</p>
        <p v-if="callConfirm.held" class="ost-sheet-held" data-testid="ost-held-line">
          {{ tp('ourstate.thread.heldLine', 'You hold {amt} {ccy}.', { amt: callConfirm.held, ccy: actingCurrencyLabel || '' }) }}
          <span v-if="callShort" class="ost-sheet-short" data-testid="ost-held-short">{{ t('ourstate.thread.heldShort', 'That is less than this call needs.') }}</span>
        </p>
        <!-- §ONBOARDQOL P2 (2026-09-02) — a wall must carry a door: when the purse is
             genuinely short (both numbers read, §RAT) the sheet points at the ONE funding
             rail this registry has (My Agents → REQUEST, opened via ?fund=1). -->
        <router-link v-if="callShort" :to="{ path: '/my-agents', query: { fund: '1' } }"
                     class="ost-sheet-door" data-testid="ost-fund-door">
          {{ tp('ourstate.thread.fundDoor', 'Request {ccy} from this registry &rsaquo;', { ccy: actingCurrencyLabel || '' }) }}
        </router-link>
        <p v-if="callConfirm.quote && !callConfirm.quote.can_buy" class="ost-sheet-refuse" data-testid="ost-quote-refuse">{{ callConfirm.quote.reason }}</p>
        <div class="ost-sheet-btns">
          <button class="ost-btn" @click="callConfirm = null">{{ t('common.cancel', 'Cancel') }}</button>
          <button class="ost-btn ost-accept" data-testid="ost-call-go"
                  :disabled="serviceBusy || callShort || (callConfirm.quote ? !callConfirm.quote.can_buy : false)"
                  @click="runServiceCall">{{ t('ourstate.thread.callNow', 'Call') }}</button>
        </div>
      </div>
    </div>

    <!-- §DEALTHREADS — the proposal composer. Structured terms, posted as a
         card nothing trusts; a supersedes ref makes it a counter. -->
    <div v-if="proposeOpen" class="ost-sheet-veil" @click.self="proposeOpen = false">
      <div class="ost-sheet" role="dialog" :aria-label="t('ourstate.thread.proposeTitle', 'Propose terms')" data-testid="ost-propose-sheet">
        <h3>{{ proposeForm.supersedes ? t('ourstate.thread.counterTitle', 'Counter terms') : t('ourstate.thread.proposeTitle', 'Propose terms') }}</h3>
        <input v-model="proposeForm.title" class="ost-sheet-input" maxlength="200"
               :placeholder="t('ourstate.thread.proposeTitlePh', 'What the engagement is')" data-testid="ost-propose-title" />
        <div class="ost-propose-row">
          <input v-model="proposeForm.total" type="number" min="0" step="any" class="ost-sheet-input ost-propose-num"
                 :placeholder="t('ourstate.thread.proposeTotalPh', 'Total (optional)')" data-testid="ost-propose-total" />
          <span class="ost-propose-ccy">{{ actingCurrencyLabel }}</span>
        </div>
        <textarea v-model="proposeForm.note" class="ost-sheet-input" rows="3" maxlength="2000"
                  :placeholder="t('ourstate.thread.proposeNotePh', 'Scope, milestones, anything else (optional)')" data-testid="ost-propose-note"></textarea>
        <p class="ost-sheet-price">{{ t('ourstate.thread.proposeNote', 'Terms are conversation — money only moves through the offer door, which re-reads everything.') }}</p>
        <div class="ost-sheet-btns">
          <button class="ost-btn" @click="proposeOpen = false">{{ t('common.cancel', 'Cancel') }}</button>
          <button class="ost-btn ost-accept" :disabled="proposeBusy || !proposeForm.title.trim()"
                  data-testid="ost-propose-post" @click="submitPropose">
            {{ proposeBusy ? t('ourstate.thread.posting', 'Posting…') : t('ourstate.thread.proposePost', 'Post terms') }}</button>
        </div>
      </div>
    </div>

    <!-- §DEALTHREADS — the engage confirm ("use these terms"): the OFFER moment.
         Same shape as the service-call confirm: acting context, the terms, one
         deliberate button. The offer opens/reuses THIS thread (open_thread). -->
    <div v-if="engageConfirm" class="ost-sheet-veil" @click.self="engageConfirm = null">
      <div class="ost-sheet" role="dialog" :aria-label="t('ourstate.thread.engageTitle', 'Send contract offer')" data-testid="ost-engage-confirm">
        <ActingContextNotice strong />
        <h3>{{ t('ourstate.thread.engageTitle', 'Send contract offer') }}</h3>
        <p class="ost-sheet-ask">{{ engageConfirm.title }}</p>
        <p class="ost-sheet-price" data-testid="ost-engage-total">
          <template v-if="engageConfirm.total">{{ engageConfirm.total }} {{ engageConfirm.currency || actingCurrencyLabel }}</template>
          <template v-else>{{ t('ourstate.thread.engageCardPrice', "The agent's card price applies.") }}</template>
        </p>
        <p v-if="engageErr" class="ost-sheet-refuse" data-testid="ost-engage-err">{{ engageErr }}</p>
        <div class="ost-sheet-btns">
          <button class="ost-btn" @click="engageConfirm = null">{{ t('common.cancel', 'Cancel') }}</button>
          <button class="ost-btn ost-accept" :disabled="engageBusy" data-testid="ost-engage-go" @click="runEngage">
            {{ engageBusy ? t('ourstate.thread.engaging', 'Sending…') : t('ourstate.thread.engageGo', 'Send offer') }}</button>
        </div>
      </div>
    </div>

    <!-- /audit — the local-only trust card. Posts nothing (battery-asserted). -->
    <div v-if="auditOpen" class="ost-sheet-veil" @click.self="auditOpen = false">
      <div class="ost-sheet" role="dialog" :aria-label="t('ourstate.thread.audit', 'Background check')" data-testid="ost-audit">
        <h3>{{ t('ourstate.thread.audit', 'Background check') }}</h3>
        <OurStateIdentity v-if="auditDid" ptype="agent" :pid="auditDid" size="lg" show-name />
        <TrustLinesRow :did="auditDid" />
        <!-- §OURSTATE-5b — the one part of /audit that is NOT composed locally:
             whether this stand-in may commit anything, re-derived from the
             capability grant and the liability mandate at read time. Asking is
             the point — "authorized up to 500 BVT" has to be checkable. -->
        <div v-if="auditAuthority" class="ost-authority" data-testid="ost-authority">
          <p class="ost-auth-line">{{ auditAuthority.sentence }}</p>
          <p v-if="auditAuthority.authorized" class="ost-audit-note" data-testid="ost-auth-ceiling">
            {{ tp('ourstate.thread.authCeiling', 'Ceiling {amt} {ccy} · expires {when} · mandate {mid}',
                  { amt: auditAuthority.ceiling, ccy: auditAuthority.currency,
                    when: (auditAuthority.expires_at || '').slice(0, 16).replace('T', ' '),
                    mid: auditAuthority.mandate?.mandate_id || '—' }) }}
          </p>
          <p v-else class="ost-audit-note" data-testid="ost-auth-reason">
            {{ tp('ourstate.thread.authReason', 'Reason: {why}', { why: auditAuthority.reason || '—' }) }}</p>
        </div>
        <p class="ost-audit-note">{{ t('ourstate.thread.auditNote', 'Public data only. Composed locally — nothing was posted, nobody was notified.') }}</p>
        <button class="ost-btn" @click="auditOpen = false">{{ t('common.close', 'Close') }}</button>
      </div>
    </div>

    <!-- §OURSTATE-7 B — /help. Four groups, four colours, each stating its own
         rule; commands that do not work HERE are dimmed WITH the reason rather
         than hidden, because "not here" and "does not exist" are different
         facts and a list that silently shrinks teaches the wrong closed set. -->
    <div v-if="helpOpen" class="ost-sheet-veil" @click.self="helpOpen = false">
      <div class="ost-sheet ost-help" role="dialog"
           :aria-label="t('ourstate.help.title', 'Commands')" data-testid="ost-help">
        <h3>{{ t('ourstate.help.title', 'Commands') }}</h3>
        <section v-for="g in helpGroups" :key="g.group" class="ost-help-group"
                 :class="`ost-help-${g.group}`" :data-testid="`ost-help-group-${g.group}`">
          <p class="ost-help-head">{{ helpLabel(g.group) }}</p>
          <p class="ost-help-rule">{{ helpRule(g.group) }}</p>
          <!-- §CHATCOHERE A4 (2026-09-01) — a cold start met 27 commands, ~21 of
               them dimmed, in one scroll. The §OURSTATE-7 law above stands and is
               deliberately NOT undone: nothing is hidden and nothing pretends not
               to exist. A group where NOTHING applies here is COLLAPSED instead,
               behind a control that states how many there are and why none of them
               are available — so the closed set is still one tap away, and a first
               reader is not asked to scroll past it to reach what works. -->
          <button v-if="helpGroupOff(g) && !helpExpanded.has(g.group)" type="button"
                  class="ost-help-more" :data-testid="`ost-help-more-${g.group}`"
                  @click="helpExpanded.add(g.group)">
            {{ tp('ourstate.help.moreHere', '{n} more — none apply here. Show', { n: g.items.length }) }}
          </button>
          <template v-if="!helpGroupOff(g) || helpExpanded.has(g.group)">
          <button v-for="c in g.items" :key="c.cmd" class="ost-help-row"
                  :class="{ off: !!c.unavailable }" :data-testid="`ost-help-${c.cmd.slice(1)}`"
                  :disabled="!!c.unavailable" @click="helpPick(c.cmd, c.unavailable)">
            <span class="ost-help-cmd">{{ c.usage }}</span>
            <span class="ost-help-gloss">{{ t(c.glossKey, c.glossFallback) }}</span>
            <span v-if="c.unavailable" class="ost-help-why"
                  :data-testid="`ost-help-why-${c.cmd.slice(1)}`">{{ helpWhy(c.unavailable) }}</span>
          </button>
          </template>
        </section>
        <p class="ost-audit-note">{{ t('ourstate.help.footnote',
          'Every command opens a door. None of them sends, pays or signs by itself.') }}</p>
        <button class="ost-btn" @click="helpOpen = false">{{ t('common.close', 'Close') }}</button>
      </div>
    </div>

    <!-- §OURSTATE-6 — /here. States its own SCOPE: a room answers with the
         registry's live member sheet, a pair answers with the two of you, and
         a failed read says so instead of falling back to the smaller claim. -->
    <div v-if="hereOpen" class="ost-sheet-veil" @click.self="hereOpen = false">
      <div class="ost-sheet" role="dialog" data-testid="ost-here-sheet">
        <h3>{{ hereScope === 'room'
              ? t('ourstate.here.titleRoom', 'Everyone who opened this room')
              : t('ourstate.here.titlePair', 'In this conversation') }}</h3>
        <p v-if="hereBusy" class="ost-audit-note">{{ t('common.loading', 'Loading…') }}</p>
        <p v-else-if="hereScope === 'unreadable'" class="ost-audit-note" data-testid="ost-here-unreadable">
          {{ t('ourstate.here.unreadable', 'Could not read who is here. That is a fact about the read, not about the room.') }}</p>
        <template v-else>
          <div v-for="(h, i) in hereRows" :key="h.ptype + h.pid + i" class="ost-here-row"
               :data-testid="`ost-here-${i}`">
            <OurStateIdentity :ptype="h.ptype" :pid="h.pid" :fallback-name="h.fallbackName"
                              size="sm" :show-name="true" />
            <span v-if="h.note" class="ost-here-note">{{ h.note }}</span>
          </div>
          <p class="ost-audit-note">{{ hereScope === 'room'
            ? t('ourstate.here.roomNote', 'Roles are read live from the organization on every request.')
            : t('ourstate.here.pairNote', 'Where the thread is hosted. It does not say where the other side is homed.') }}</p>
        </template>
        <button class="ost-btn" data-testid="ost-here-close" @click="hereOpen = false">
          {{ t('cta.close', 'Close') }}</button>
      </div>
    </div>

    <!-- §OURSTATE-6 — the disappearing timer. Both sides see the choice and
         both are told when it changes, because a timer one side set privately
         would be a promise about the other's copy that nobody can keep. -->
    <div v-if="timerOpen" class="ost-sheet-veil" @click.self="timerOpen = false">
      <div class="ost-sheet" role="dialog" data-testid="ost-timer-sheet">
        <h3>{{ t('ourstate.thread.timerTitle', 'Disappearing messages') }}</h3>
        <p class="ost-audit-note">{{ t('ourstate.thread.timerNote',
          'This deletes messages from this registry on a schedule. It cannot reach a copy the other side already saved, and both of you are told when it changes.') }}</p>
        <p v-if="!timerEditable" class="ost-audit-note" data-testid="ost-timer-readonly">{{ t('ourstate.settings.timerReadOnly',
          "In an organization's room, an owner or an admin sets the timer.") }}</p>
        <button v-for="c in RETENTION_CHOICES" :key="String(c.h)" class="ost-btn"
                :data-testid="`ost-timer-${c.h ?? 'off'}`"
                :class="{ 'ost-timer-on': retentionHours === c.h }" :disabled="!timerEditable"
                @click="setRetention(c.h)">{{ t(c.k, c.d) }}</button>
        <button class="ost-btn ost-ghost-btn" data-testid="ost-timer-cancel" @click="timerOpen = false">{{ t('common.cancel', 'Cancel') }}</button>
      </div>
    </div>

    <!-- §OURSTATE-6 — ask-back confirm. Named as what it is: a request the
         other side is free to ignore. No "undo", because there is none. -->
    <div v-if="askBackOpen" class="ost-sheet-veil" @click.self="askBackOpen = false">
      <div class="ost-sheet" role="dialog" data-testid="ost-askback-sheet">
        <h3>{{ t('ourstate.thread.askBackTitle', 'Ask them to send it back?') }}</h3>
        <p>{{ tp('ourstate.thread.askBackLine',
                 'This posts a request for {amt} {ccy}. It is a request: the payment itself is final and they are free to ignore this.',
                 { amt: askBackCard?.amount || '', ccy: askBackCard?.currency || '' }) }}</p>
        <div class="ost-sheet-btns">
          <button class="ost-btn" @click="askBackOpen = false">{{ t('common.cancel', 'Cancel') }}</button>
          <button class="ost-btn" data-testid="ost-askback-go" @click="sendAskBack">
            {{ t('ourstate.thread.askBackGo', 'Post the request') }}</button>
        </div>
      </div>
    </div>

    <!-- Block confirm -->
    <div v-if="blockConfirm" class="ost-sheet-veil" @click.self="blockConfirm = false">
      <div class="ost-sheet" role="dialog" data-testid="ost-block-confirm">
        <h3>{{ t('ourstate.thread.blockTitle', 'Block this counterparty?') }}</h3>
        <p>{{ t('ourstate.thread.blockLine', 'The thread leaves your list and nothing from them reaches you. They are not told.') }}</p>
        <div class="ost-sheet-btns">
          <button class="ost-btn" @click="blockConfirm = false">{{ t('common.cancel', 'Cancel') }}</button>
          <button class="ost-btn ost-danger" data-testid="ost-block-go" @click="doBlock">{{ t('ourstate.thread.block', 'Block') }}</button>
        </div>
      </div>
    </div>

    <!-- V0652 (ak): burn for you, its sentence first; notifications; the room's settings; leaving; your chat settings -->
    <ChatBurnConfirm v-if="burnOpen" :hosting="hosting" @cancel="burnOpen = false" @burn="burnNow" />
    <!-- V0652 (aa): a card's history (who, when, what changed), read when asked -->
    <ChatCardHistory v-if="cardHistoryFor" :token="token" :conversation-id="convId" :message-id="cardHistoryFor.id"
                     :title="cardHistoryFor.title" @close="cardHistoryFor = null" />
    <ChatNotifySheet v-if="notifyOpen" :kind="settingsKind" :title="settingsTitle" :muted="mutedNow" :muted-until="mutedUntil"
                     :busy="notifyBusy" :error="notifyErr" @cancel="notifyOpen = false" @save="saveNotify" />
    <ChatRoomSettings v-if="roomSettingsOpen && room" ref="roomSettingsEl" :title="settingsTitle" :topic="room.topic"
                      :rules="room.genesis?.stated" :mode="room.mode" :is-operator="!!room.my_is_operator"
                      :assistant-present="!!room.assistant_present" :busy="roomBusy" :error="roomErr"
                      @close="roomSettingsOpen = false" @mode="stageModeChange" @save="saveRoomText" />
    <div v-if="leaveConfirm" class="ost-sheet-veil" @click.self="leaveConfirm = false">
      <div class="ost-sheet" role="alertdialog" data-testid="ost-leave-confirm">
        <h3>{{ settingsKind === 'room' ? t('ourstate.settings.leaveRoomTitle', 'Leave this room?') : t('ourstate.settings.leaveChatTitle', 'Leave this chat?') }}</h3>
        <p>{{ settingsKind === 'room'
          ? t('ourstate.settings.leaveRoomLine', 'It leaves your list and its messages stop reaching you. Open it again from your organization to come back. The room is not told.')
          : t('ourstate.settings.leaveChatLine', 'It leaves your list and nothing in it reaches you until you start a chat with them again. They are not told.') }}</p>
        <div class="ost-sheet-btns">
          <button class="ost-btn" data-testid="ost-leave-cancel" @click="leaveConfirm = false">{{ t('common.cancel', 'Cancel') }}</button>
          <button class="ost-btn ost-danger" data-testid="ost-leave-go" :disabled="leaveBusy" @click="doLeave">{{ t('ourstate.settings.leave', 'Leave') }}</button>
        </div>
      </div>
    </div>
    <ChatYouPanel v-if="youOpen" :surface="wideMenu ? 'drawer' : 'sheet'" :push-state="pushState" :push-busy="pushBusy"
                  :push-msg="pushMsg" :in-pocket="inPocket" @close="youOpen = false" @enable-push="enablePushFromPanel" />

    <!-- §OURSTATE-2 members sheet: who has opened the room, live org roles,
         and the operator ops the brain OFFERS (server re-gates live). -->
    <div v-if="membersOpen" class="ost-sheet-veil" @click.self="membersOpen = false">
      <div class="ost-sheet" role="dialog" :aria-label="t('ourstate.rooms.members', 'Members')" data-testid="ost-members">
        <h3>{{ t('ourstate.settings.membersTitle', 'Who has opened this room') }}</h3>
        <p class="ost-audit-note">{{ t('ourstate.rooms.membersNote', 'Members who have opened the room. Roles are the org roster, live.') }}
          <router-link to="/organization" class="ost-roster-door" data-testid="ost-roster" @click="membersOpen = false">{{ t('ourstate.settings.roster', "The organization's whole roster") }} ›</router-link></p>
        <div v-for="mb in members" :key="mb.ptype + ':' + (mb.agent_did || mb.developer_id)" class="ost-member-row"
             :data-testid="`ost-member-${mb.developer_id || mb.agent_did}`">
          <span class="ost-member-name">{{ mb.name || mb.agent_did || ('dev ' + mb.developer_id) }}
            <span v-if="mb.org_role" class="ost-role">{{ mb.org_role }}</span>
            <Icon v-if="!mb.can_post" name="mdi:volume-off" class="ost-mutedico" />
          </span>
          <span class="ost-member-ops">
            <button v-for="op in memberOffers(mb)" :key="op.key" class="ost-chipbtn"
                    :class="{ danger: op.destructive }" :data-testid="`ost-op-${op.key}`"
                    @click="onMemberOp(op, mb)">{{ t('ourstate.rooms.op.' + op.key, op.label) }}</button>
          </span>
          <!-- V0654 (aq): what of the room wakes this member; the room's owner, signed in, switches a session's -->
          <WakeModeSwitch v-if="membersCanSetWake && mb.ptype === 'agent' && !mb.is_me" class="ost-member-wake"
                          :mode="mb.wake_mode || 'listen'" :who="mb.name || mb.agent_did" :testid="mb.agent_did"
                          :busy="wakeBusy === mb.key" @set="(m) => setMemberWake(mb, m)" />
          <span v-else-if="mb.wake_mode && mb.wake_mode !== 'listen'" class="ost-wake-chip"
                :data-testid="`ost-wake-${mb.developer_id || mb.agent_did}`">{{ wakeWord(mb.wake_mode) }}</span>
        </div>
        <button class="ost-btn" @click="membersOpen = false">{{ t('common.close', 'Close') }}</button>
      </div>
    </div>

    <!-- §OURSTATE-2 room-op confirm: destructive acts HOLD to execute; the
         rest confirm with a tap. Every act lands as a visible system row. -->
    <div v-if="roomConfirm" class="ost-sheet-veil" @click.self="roomConfirm = null">
      <div class="ost-sheet" role="dialog" data-testid="ost-room-confirm">
        <h3>{{ t('ourstate.rooms.confirm.' + roomConfirm.action, roomConfirmTitle) }}</h3>
        <p v-if="roomConfirm.targetName" class="ost-sheet-ask" data-testid="ost-room-target">{{ roomConfirm.targetName }}</p>
        <p v-if="roomConfirm.action === 'kick'" class="ost-audit-note">
          {{ t('ourstate.rooms.kickNote', 'Removes from this ROOM only. Org membership is untouched — that lives on the org page.') }}</p>
        <textarea v-if="roomConfirm.action === 'motd' || roomConfirm.action === 'topic'"
                  v-model="roomConfirm.value" class="ost-input" rows="3" data-testid="ost-room-value"
                  :maxlength="roomConfirm.action === 'motd' ? 2000 : 200" />
        <p v-if="roomConfirm.action === 'assistant_on'" class="ost-sheet-ask" data-testid="ost-assistant-scope">
          {{ t('ourstate.rooms.assistantScope', 'The assistant answers only when addressed with @assistant, and reads only records this organization already holds: room receipts, the roster, the treasury balance. It never reads other rooms and never volunteers. Everyone sees a system row when it is added or removed.') }}</p>
        <p v-if="roomConfirm.action === 'assistant_off'" class="ost-sheet-ask">
          {{ t('ourstate.rooms.assistantOffAsk', 'The assistant stops answering from the next message. A system row records the removal.') }}</p>
        <p v-if="roomConfirm.action === 'mode'" class="ost-sheet-ask">
          {{ roomConfirm.value === 'announce'
            ? t('ourstate.rooms.modeToAnnounce', 'Announce-only: org owners and admins post; everyone reads.')
            : t('ourstate.rooms.modeToOpen', 'Open: every member posts.') }}</p>
        <p v-if="roomErr" class="ost-sheet-refuse" data-testid="ost-room-err">{{ roomErr }}</p>
        <div class="ost-sheet-btns">
          <button class="ost-btn" @click="roomConfirm = null">{{ t('common.cancel', 'Cancel') }}</button>
          <button v-if="roomConfirm.destructive" class="ost-btn ost-danger ost-hold" data-testid="ost-room-hold"
                  @pointerdown="roomHoldStart" @pointerup="roomHoldCancel" @pointerleave="roomHoldCancel" @pointercancel="roomHoldCancel">
            {{ t('ourstate.rooms.holdToExecute', 'Hold to execute') }}
            <span class="ost-burn-bar" :style="{ width: roomHoldPct + '%' }" aria-hidden="true"></span></button>
          <button v-else class="ost-btn ost-accept" data-testid="ost-room-go" :disabled="roomBusy"
                  @click="executeRoomOp">{{ t('common.confirm', 'Confirm') }}</button>
        </div>
      </div>
    </div>

    <!-- §ROOMBRAIN — the privacy panel: no new facts, one honest composition. -->
    <div v-if="privacyOpen" class="ost-sheet-veil" @click.self="privacyOpen = false">
      <div class="ost-sheet" role="dialog" :aria-label="t('ourstate.privacy.title', 'Who can read this thread')" data-testid="ost-privacy-sheet">
        <h3>{{ t('ourstate.privacy.title', 'Who can read this thread') }}</h3>
        <ul class="ost-privacy-list">
          <li><Icon name="mdi:account-group" />
            {{ t('ourstate.privacy.participants', 'Everyone in this thread — every message names its author, forever.') }}</li>
          <li data-testid="ost-privacy-host"><Icon name="mdi:server" />
            <template v-if="hosting?.copies?.length">{{ tp('ourstate.privacy.hostCopies',
                  'The operators of {reg}, which hosts this thread, and of {copies}, which keeps a copy — it is not end-to-end encrypted.',
                  { reg: hosting.registry, copies: hosting.copies.join(', ') }) }}</template>
            <template v-else>{{ tp('ourstate.privacy.host', 'The operator of {reg} — this thread is hosted there and is not end-to-end encrypted.',
                  { reg: hosting?.registry || t('pocket.send.thisRegistry', 'this registry') }) }}</template></li>
          <li v-if="room?.assistant_present" data-testid="ost-privacy-assistant"><Icon name="mdi:robot-outline" />
            {{ t('ourstate.privacy.assistant', '@assistant — answers when addressed, reading org records only (receipts, roster, treasury).') }}</li>
          <li v-if="room?.transparency_public" data-testid="ost-privacy-public"><Icon name="mdi:earth" />
            {{ t('ourstate.privacy.public', 'The public — work RECORDS only (receipts, system rows, the topic). Written messages stay private.') }}</li>
          <li v-for="g in liveReviewGrants" :key="g.grant_id" data-testid="ost-privacy-grant"><Icon name="mdi:lifebuoy" />
            {{ tp('ourstate.privacy.grant', 'The support desk — read-only, for ticket #{id}; the grant dies with the ticket.',
                  { id: String(g.ticket_id) }) }}</li>
        </ul>
        <p v-if="!privacyGrantsKnown" class="ost-sheet-refuse" data-testid="ost-privacy-unknown">
          {{ t('ourstate.privacy.grantsUnknown', 'Support-review state could not be read just now — an honest gap, not a "nobody".') }}</p>
        <p class="ost-audit-note" data-testid="ost-privacy-retention">
          {{ retentionLabel || t('ourstate.privacy.noRetention', 'No disappearing timer — messages stay until deleted or burned.') }}</p>
        <div class="ost-sheet-btns">
          <button class="ost-btn" @click="privacyOpen = false">{{ t('common.close', 'Close') }}</button>
        </div>
      </div>
    </div>

    <!-- §OURSTATE-2 mixed-speaker dm: WHO says the next message. Each message
         keeps its author forever (immutable provenance) — this only chooses
         the next one, and only among principals you actually hold. -->
    <div v-if="speakerPickerOpen" class="ost-sheet-veil" @click.self="speakerPickerOpen = false">
      <div class="ost-sheet" role="dialog" :aria-label="t('ourstate.speaker.title', 'Speak as')" data-testid="ost-speaker-picker">
        <h3>{{ t('ourstate.speaker.title', 'Speak as') }}</h3>
        <p class="ost-audit-note">{{ t('ourstate.speaker.note', 'Every message keeps the author it was sent with. Switching changes only what comes next.') }}</p>
        <!-- V0654 (ap): your assistant for the identity this thread sends with, switched per identity and per room, here -->
        <div v-if="assistOffered" class="ost-assist-row" data-testid="ost-assist-row">
          <button type="button" role="switch" class="ost-assist-switch" :class="{ on: assistOn }"
                  :aria-checked="assistOn ? 'true' : 'false'" data-testid="ost-assist-switch" @click="toggleAssist">
            <Icon name="mdi:creation" class="ost-assist-switch-mark" />
            <span class="ost-assist-switch-label">{{ tp('ourstate.assist.switch', 'AI assistant for {who}', { who: assistWhoName }) }}</span>
            <span class="ost-assist-switch-state">{{ assistOn ? t('ourstate.assist.on', 'on') : t('ourstate.assist.off', 'off') }}</span>
          </button>
          <p class="ost-audit-note">{{ tp('ourstate.assist.note', 'While it is on, what you type in this room goes to your assistant, not to the room. Only you see your request; the answer is posted as {who}, marked as written by the assistant.', { who: assistWhoName }) }}</p>
        </div>
        <!-- §OURSTATE-6 — THE SAME LIST THE HEADER USES. It used to be a bare
             v-for with no search and no scroll container, holding a SECOND
             selection that could disagree with "Acting as" in the header. With
             640 stored credentials it was unusable and the two controls read
             differently on the same screen. His ruling: they must never be out
             of sync — so there is now one list and one choice, and picking here
             sets the acting agent every other surface already reads. -->
        <p class="ost-audit-note">{{ t('ourstate.speaker.vsActingThread',
          'Choosing an agent also makes it the agent you act as in the header, which decides the registry and currency your money moves on. This thread remembers the choice; every other thread speaks as you until you choose there.') }}</p>
        <AgentSwitchList show-you :you-selected="speakAsHuman"
                         @pick-you="pickHumanSpeaker" @switched="onSpeakerSwitched" />
        <button class="ost-btn" @click="speakerPickerOpen = false">{{ t('common.close', 'Close') }}</button>
      </div>
    </div>

    <!-- /ledger — where you and this counterparty stand. LOCAL, and it says
         from how much it computed that (a number without its window lies). -->
    <!-- §SHOWCASESTOCKS — what trades right now, with LIVE prices. A read, so
         it posts nothing into the thread. -->
    <div v-if="stockListOpen" class="ost-sheet-veil" @click.self="stockListOpen = false">
      <div class="ost-sheet" role="dialog" :aria-label="t('ourstate.stocks.title', 'Trading right now')" data-testid="ost-stocks">
        <h3>{{ t('ourstate.stocks.title', 'Trading right now') }}</h3>
        <p v-if="!stockList.length" class="ost-audit-note" data-testid="ost-stocks-empty">
          {{ t('ourstate.stocks.empty', 'No listing matched.') }}</p>
        <div v-for="(ln, i) in stockList" :key="i" class="ost-stock-line" data-testid="ost-stock-line">{{ ln }}</div>
        <p class="ost-audit-note">
          {{ t('ourstate.stocks.foot', 'Prices are the market’s own: last traded, or best ask, never the launch price it started at. A figure in your currency is shown alongside where a rate is published. /listing SYM shares one into the thread.') }}</p>
        <button class="ost-btn" @click="stockListOpen = false">{{ t('common.close', 'Close') }}</button>
      </div>
    </div>

    <!-- §OURCHATBAL — your position, shown to you. A read: it posts nothing
         into the thread, because a balance is not something you share with a
         counterparty by typing a command. -->
    <div v-if="balanceOpen" class="ost-sheet-veil" @click.self="balanceOpen = false">
      <div class="ost-sheet" role="dialog"
           :aria-label="t('ourstate.balance.title', 'What you hold')" data-testid="ost-balance">
        <h3>{{ t('ourstate.balance.title', 'What you hold') }}</h3>
        <p v-if="balanceBusy" class="ost-audit-note" data-testid="ost-balance-busy">
          {{ t('common.loading', 'Loading…') }}</p>
        <div v-for="(ln, i) in balanceLines" :key="i" class="ost-stock-line"
             data-testid="ost-balance-line">{{ ln }}</div>
        <p v-if="balanceNote" class="ost-audit-note" data-testid="ost-balance-note">{{ balanceNote }}</p>
        <button class="ost-btn" @click="balanceOpen = false">{{ t('common.close', 'Close') }}</button>
      </div>
    </div>

    <div v-if="ledgerOpen" class="ost-sheet-veil" @click.self="ledgerOpen = false">
      <div class="ost-sheet" role="dialog" :aria-label="t('ourstate.ledger.title', 'Where we stand')" data-testid="ost-ledger">
        <h3>{{ t('ourstate.ledger.title', 'Where we stand') }}</h3>
        <p v-if="ledger?.empty" class="ost-audit-note" data-testid="ost-ledger-empty">
          {{ t('ourstate.ledger.empty', 'Nothing economic in the part of this thread I can see.') }}</p>
        <div v-for="l in ledger?.lines || []" :key="l.currency" class="ost-ledger-line" :data-testid="`ost-ledger-${l.currency}`">
          <span class="ost-ledger-ccy">{{ l.currency }}</span>
          <span class="ost-ledger-nums">
            <span>{{ tp('ourstate.ledger.youPaid', 'you paid {amt}', { amt: l.paidByYou.toFixed(6) }) }}</span>
            <span>{{ tp('ourstate.ledger.theyPaid', 'they paid {amt}', { amt: l.paidToYou.toFixed(6) }) }}</span>
          </span>
          <span class="ost-ledger-net" :class="{ pos: l.net > 0, neg: l.net < 0 }">
            {{ l.net > 0 ? '+' : '' }}{{ l.net.toFixed(6) }}</span>
        </div>
        <div v-if="(ledger?.open || []).length" class="ost-ledger-open" data-testid="ost-ledger-open">
          <p class="ost-ledger-openhead">{{ t('ourstate.ledger.openItems', 'Open') }}</p>
          <div v-for="(o, i) in ledger?.open || []" :key="i" class="ost-ledger-openrow">
            <span>{{ o.label }}</span>
            <span v-if="o.amount && o.currency" class="ost-ledger-openamt">{{ o.amount }} {{ o.currency }}</span>
          </div>
        </div>
        <p class="ost-audit-note" data-testid="ost-ledger-bounds">
          {{ tp('ourstate.ledger.bounds', 'From the {n} messages loaded here{clip}.', {
            n: String(ledger?.bounds.messages ?? 0),
            clip: ledger?.bounds.clipped ? t('ourstate.ledger.clipped', ' — older or burned rows are not counted') : '' }) }}
          {{ t('ourstate.ledger.localNote', 'Composed locally; nothing was posted.') }}
        </p>
        <button class="ost-btn" @click="ledgerOpen = false">{{ t('common.close', 'Close') }}</button>
      </div>
    </div>

    <!-- /work — share a pointer at an engagement you are a party to. -->
    <div v-if="workPickerOpen" class="ost-sheet-veil" @click.self="workPickerOpen = false">
      <div class="ost-sheet" role="dialog" :aria-label="t('ourstate.work.title', 'Share work')" data-testid="ost-work-picker">
        <h3>{{ t('ourstate.work.title', 'Share work') }}</h3>
        <p class="ost-audit-note">{{ t('ourstate.work.note', 'Posts a pointer. Awarding, delivering and settling stay on the work rail.') }}</p>
        <div v-if="workBusy" class="ost-audit-note">{{ t('common.loading', 'Loading…') }}</div>
        <p v-else-if="!workItems.length" class="ost-audit-note" data-testid="ost-work-empty">
          {{ t('ourstate.work.empty', 'No open contracts or guild orders on your acting agent.') }}</p>
        <button v-for="(w, i) in workItems" :key="w.kind + w.ref" class="ost-workrow" :data-testid="`ost-work-${i}`"
                @click="shareWork(w)">
          <span class="ost-workrow-title">{{ w.title }}</span>
          <span class="ost-workrow-meta">
            <span>{{ w.kind === 'guild.order' ? t('ourstate.card.guildOrder', 'Guild order') : t('ourstate.card.contractOffer', 'Contract') }}</span>
            <span v-if="w.amount && w.currency">{{ w.amount }} {{ w.currency }}</span>
            <span v-if="w.status">{{ w.status }}</span>
          </span>
        </button>
        <button class="ost-btn" @click="workPickerOpen = false">{{ t('common.close', 'Close') }}</button>
      </div>
    </div>

    <!-- PocketSend — THE one send door, prefilled by /pay and pay.request taps. -->
    <PocketSend v-if="sendEver" :open="sendOpen" mode="send" :ccy="actingCurrencyLabel || undefined"
                :initial-to="sendPrefill.to" :initial-amount="sendPrefill.amount" :initial-memo="sendPrefill.memo"
                @close="sendOpen = false" @sent="onSent" />

    <component :is="AgentDetailModal" v-if="detailEver" v-model:show="detailOpen" :agent-did="detailDid" />
  </div>
</template>

<script setup lang="ts">
import { blockTargetFor, householdJoinPrompt, identityKind, identityPid } from '@/services/chat/counterparty'
import { readAccessToken } from '@/services/accessToken'
import { ref, computed, watch, onMounted, onUnmounted, nextTick, defineAsyncComponent, inject } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useOurChatBase } from '@/composables/useOurChatBase'
import { OURCHAT_LIST_FOLD, headerArrow } from '@/services/chat/listFold'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import OurStateIdentity from '@/components/ourstate/OurStateIdentity.vue'
import UserAvatar from '@/components/common/UserAvatar.vue'
import AgentSwitchList from '@/components/pocket/AgentSwitchList.vue'
import OurStateCard from '@/components/ourstate/OurStateCard.vue'
import ChatMessageBody from '@/components/ourstate/ChatMessageBody.vue'
import ChatAssistAsk from '@/components/ourstate/ChatAssistAsk.vue'
import WakeModeSwitch from '@/components/ourstate/WakeModeSwitch.vue'
import ChatSettingsMenu from '@/components/ourstate/ChatSettingsMenu.vue'
import ChatBurnConfirm from '@/components/ourstate/ChatBurnConfirm.vue'
import ChatNotifySheet from '@/components/ourstate/ChatNotifySheet.vue'
import ChatRoomSettings from '@/components/ourstate/ChatRoomSettings.vue'
import ChatYouPanel from '@/components/ourstate/ChatYouPanel.vue'
import ChatSidePanel from '@/components/ourstate/ChatSidePanel.vue'
import ChatCardHistory from '@/components/ourstate/ChatCardHistory.vue'
import ChatBoard from '@/components/ourstate/ChatBoard.vue'
import { foldThreads, lastReplyAt, type ThreadBar } from '@/services/chat/threads'
import { applyCardUpdate, applyCardUpdates, type CardUpdate } from '@/services/chat/liveCards'
import { chatSurfaceFor, narrowPane, showSidePanel } from '@/services/chat/sidePanel'
import { muteInEffect } from '@/services/chat/notifyLevel'
import { isAsk, namesViewer, timeLabel, timeTitle } from '@/services/chat/messageText'
import { appLocale } from '@/services/appLocale'
import OurChatApprovals from '@/views/pocket/OurChatApprovals.vue'
import { liveApprovalStatus, touchesApprovals } from '@/services/chat/approvals'
import TrustLinesRow from '@/components/ourstate/TrustLinesRow.vue'
import ActingContextNotice from '@/components/common/ActingContextNotice.vue'
import PocketSend from '@/views/pocket/PocketSend.vue'
import { chatApi, type WakeMode } from '@/services/api/chat'
import { getThread, putThread, dropThread, cacheAvailable, burnDeviceNote } from '@/services/chat/localCache'
import { parseComposer, completions, commandGroups, argCompletions } from '@/services/chat/composerIntent'
import { composerCan, memberOps, roomOps, systemRowText,
         type RoomActionOffer, type RoomMemberView } from '@/services/chat/orgRoomActions'
import { buildPayRequest, buildPayReceipt, buildWorkCard, buildAgentCard, buildEngagementProposal, displayAmount } from '@/services/chat/cards'
import { discoveryService } from '@/services/api/discovery'
import { exchangeService } from '@/services/api/exchangeService'
import { buildLedger, type LedgerView } from '@/services/chat/ledger'
import { pushOptInRows } from '@/services/chat/pushOptIn'
// §SHOWCASESTOCKS — the shared price brain, so Pocket and the landing showcase
// cannot hold two different opinions about what a share costs.
import { normalizeListing, effectivePrice, priceLine, mergeTickers, trim } from '@/services/chat/stocks'
import { developerApi } from '@/services/api/developers'   // ⚠ PLURAL: developer.ts is a different module and has no balances rail
import { contractsV2Api } from '@/services/api/contractsV2'
import { useAuthStore } from '@/stores/auth'
import { usePocketAgent } from '@/composables/usePocketAgent'
import { rememberedSpeaker, rememberSpeaker, resolveSpeaker } from '@/services/chat/speakAs'
import { YOU, assistantIds, rememberAssistant, readAsks, writeAsks, type AssistAsk } from '@/services/chat/assistOn'
import { useUIStore } from '@/stores/ui'
import { usePocketLock } from '@/composables/usePocketLock'
import { useActingContext } from '@/composables/useActingContext'
import { useChatStream } from '@/composables/useChatStream'
import { useThreadCatchUp } from '@/composables/useThreadCatchUp'
import { mergeBySeq, firstUnreadIndex } from '@/services/chat/catchUp'
import { ANCHOR_MS, keepAnchored, type Anchor } from '@/services/chat/unreadAnchor'
import { useFocusTrap } from '@/composables/useFocusTrap'
import { devicePushApi } from '@/services/api/devicePush'
import apiClient from '@/services/api/client'
import { useI18n } from '@/composables/useI18n'

const { t, tp } = useI18n()
const route = useRoute()
const router = useRouter()
const { base } = useOurChatBase()
const auth = useAuthStore()
const { credAgents, ensureAgentFor, noAgentReason, sealedLocked } = usePocketAgent()
// §PHONESTART — a hint shown while the vault holds no agent gets a create door beside it.
const uiStore = useUIStore()
const lock = usePocketLock()
const { actingCurrencyLabel } = useActingContext()
/* §CHATCOHERE D9 — THE one predicate for "is there a purse this surface can read".
   Read by `composerCtx` (what /help offers) and by `showBalance()` (what actually
   answers), so the offer and the handler cannot disagree — which is exactly how
   /help came to advertise `/balance` as impossible while it worked.
   ⚠ Declared HERE, beside `auth`, and reading ONLY `auth` — `speakerDid` resolves
   to the same `activeAgent.did` but lives 1,100 lines lower, and a computed that
   reaches down the file is the §HIRECOHERE temporal-dead-zone shape. */
const walletDid = computed<string>(() => String((auth as any).activeAgent?.did || ''))

const convId = computed(() => String(route.params.id || ''))
// V0651 (y): the request a link opened (a push, Pocket's Approvals): the pinned panel shows it highlighted
const focusApprovalId = computed(() => String(route.query.approval || ''))
const token = computed(() => (auth as any).token || readAccessToken() || '')

const messages = ref<any[]>([])
const myState = ref('active')
const kind = ref('dm')
const counterparty = ref<any | null>(null)
const room = ref<any | null>(null)        // §OURSTATE-2: org-room state from the page
const genesisOpen = ref(false)
const serviceInflight = ref(false)
const hasOlder = ref(false)
const lastSeq = ref(0)
const err = ref('')
const menuOpen = ref(false)
const muted = ref(false)
const scrollEl = ref<HTMLElement | null>(null)
// V0650 (l): the pinned approvals panel, told when an approval card arrives in the thread
const approvalsPanel = ref<{ refresh: () => Promise<void>; openList: () => void } | null>(null)
// V0652 (ad): the console's chat measures its OWN pane (the sidebar and the conversation list take their share of the
// window) to decide whether an organization room's side panel shows beside the column; Pocket keeps its own layout
const rootEl = ref<HTMLElement | null>(null)
const paneWidth = ref(0)
const surface = computed(() => chatSurfaceFor(base.value))
const sideOn = computed(() => showSidePanel(paneWidth.value, kind.value, room.value?.org_id, surface.value))
const approvalsCount = ref<number | null>(null)
/* V0653 (al), his words in the sessions' room (seq 686): the arrow over the chat "just leave[s] the chat and says pick
   a conversation". Inside the shell's two panes it folds and opens the list instead (OurChatShell keeps the choice);
   on one pane, or outside the shell, it leaves the thread for the list as before. */
const listFold = inject(OURCHAT_LIST_FOLD, null)
const arrowAct = computed(() => headerArrow(!!listFold?.twoPane.value, !!listFold?.folded.value))
const arrowLabel = computed(() => arrowAct.value === 'fold-list'
  ? t('ourstate.list.fold', 'Fold the conversation list')
  : arrowAct.value === 'open-list' ? t('ourstate.list.unfold', 'Show the conversation list') : t('common.back', 'Back'))
function onArrow() {
  if (arrowAct.value === 'leave' || !listFold) void router.push(base.value)
  else listFold.toggle()
}
let paneRo: ResizeObserver | null = null
function measurePane() { paneWidth.value = rootEl.value?.clientWidth || 0 }
const inputEl = ref<HTMLTextAreaElement | null>(null)

const isAgentThread = computed(() => kind.value === 'agent_service')
/* §OURSTATE-7 D — declared HERE, beside its sibling, because the composer's
   placeholder and `send()` both read it and a computed that is only defined
   further down is one refactor away from a temporal-dead-zone throw. */
const isSupportThread = computed(() => kind.value === 'support')
const counterpartyDid = computed(() =>
  counterparty.value?.ptype === 'agent' ? counterparty.value.agent_did : null)

/* ── load + realtime ── */
// §COCKPITDESK (2026-10-15): every read is for the thread on screen when it answers. Switching threads while one was
// in flight let the earlier thread's answer land under the later one: its messages painted there, written into the
// later thread's device cache, and the later thread marked read up to the earlier one's last message.
async function load() {
  const id = convId.value
  endAnchor()   // V0654: a reload (a switch, the socket back) starts from its own scroll
  // §OURSTATE-5d — the cache is a HEAD START, never the truth: paint what this
  // device already holds (only ever present when the sealed vault could
  // encrypt it), then let the server's answer replace it.
  try {
    const cached = await getThread(id)
    if (id !== convId.value) return
    if (cached?.messages?.length && !messages.value.length) {
      messages.value = cached.messages
      await nextTick(); scrollBottom()
    }
  } catch { /* a cache miss is not an event */ }
  try {
    const r = await chatApi.getMessages(token.value, id, undefined, 40, joinConfirmed.value)
    if (id !== convId.value) return
    joinPrompt.value = null
    messages.value = r.messages || []
    myState.value = r.my_state || 'active'
    kind.value = r.kind || 'dm'
    counterparty.value = r.counterparty || null
    room.value = r.room || null
    muted.value = !!r.muted                     // V0652 (ak): the thread's mute, read with it (the menu shows it)
    mutedUntil.value = r.muted_until ?? null    // and when a mute set for a while ends
    serviceInflight.value = !!r.service_inflight
    lastSeq.value = Number(r.last_seq || 0)
    pageBound.value = Number(r.page_bound || 40)
    hosting.value = r.hosting || null
    retentionHours.value = r.retention_hours ?? null
    // Best-effort and never blocking: the thread paints from the stored cards
    // first, then upgrades any receipt still mid-flight.
    void refreshSettlements()
    void loadServicePrice()
    void loadSupport()
    hasOlder.value = messages.value.length > 0 && messages.value[0].seq > 1 &&
      messages.value.length >= (r.page_bound || 40)
    err.value = ''
    readFloor.value = Number(r.my_last_read_seq || 0)
    const unreadAt = firstUnreadIndex(messages.value as any, Number(r.my_last_read_seq || 0), (m: any) => isMine(m))
    unreadFromSeq.value = unreadAt >= 0 ? Number(messages.value[unreadAt].seq) : null
    unreadCount.value = unreadAt >= 0 ? messages.value.length - unreadAt : 0
    await nextTick()
    if (id !== convId.value) return
    if (unreadFromSeq.value != null) { scrollToUnread(); holdAnchor() } else scrollBottom()
    // No key, no cache — putThread writes nothing rather than falling back to
    // plaintext, and says so by returning false.
    if (id !== convId.value) return
    void putThread(id, messages.value).catch(() => {})
    if (lastSeq.value > 0) void chatApi.markRead(token.value, id, lastSeq.value).catch(() => {})
  } catch (e: any) {
    if (id !== convId.value) return
    // §TWOAGENT G1 (V0437): the server asks before it announces an owner to the other side of a cross-registry thread
    const ask = householdJoinPrompt(e)
    if (ask) { joinPrompt.value = ask; return }
    err.value = e?.detail || e?.message || 'load failed'
  }
}

/* §TWOAGENT G1 (V0437) — opening an agent's cross-registry thread as its OWNER is a visible join: ask first. */
const joinPrompt = ref<string | null>(null)
const joinConfirmed = ref(false)
function confirmJoin() { joinConfirmed.value = true; joinPrompt.value = null; void load() }

// §FESUITE V0578: a failed older read set hasOlder false, so "Load older" went away as if the thread's start had been
// reached; it says the read failed now (Try again), and only an answered empty page ends the history.
const olderFailed = ref(false)
async function loadOlder() {
  const id = convId.value
  const first = messages.value[0]?.seq
  if (!first) return
  let r: any
  try { r = await chatApi.getMessages(token.value, id, first) } catch { if (id === convId.value) olderFailed.value = true; return }
  if (id !== convId.value) return   // an older page of a thread no longer on screen
  olderFailed.value = false
  if (r?.messages?.length) {
    messages.value = [...r.messages, ...messages.value]
    hasOlder.value = r.messages[0].seq > 1 && r.messages.length >= (r.page_bound || 40)
  } else hasOlder.value = false
}

/* V0652 (aa): a card updated in place, applied by its rev (a newer one replaces the card; one arriving twice or late
   changes nothing), from the socket, the long-poll's updates or a catch-up read */
function applyUpdate(u: CardUpdate | null | undefined) {
  const r = applyCardUpdate(messages.value as any, u)
  if (r.changed) messages.value = r.messages as any
  // V0654 (aq), item 18: a request card that changed (withdrawn) leaves the pinned list: it reads the list again
  if (r.changed && touchesApprovals({ kind: 'card', card: (u as any)?.card })) void approvalsPanel.value?.refresh()
}
const cardHistoryFor = ref<{ id: string; title: string } | null>(null)
function openCardHistory(m: any) {
  cardHistoryFor.value = { id: String(m?.id || ''), title: String(m?.card?.data?.title || '') }
}

const chatStream: any = useChatStream({
  onMessage: (env) => { if (env.conversation_id === convId.value) ingest(env.message) },
  onPing: (env) => { if (env.conversation_id === convId.value) ingest(env.message) },
  onCardUpdate: (env) => { if (env.conversation_id === convId.value) applyUpdate(env.message as any) },
  onBoardUpdate: (env) => {
    if (env.conversation_id !== convId.value || !room.value) return
    const cur = room.value.board || {}
    if (Number(env.board?.rev || 0) > Number(cur.rev || 0)) onBoardUpdate(env.board)
  },
  onResync: () => { void load(); void approvalsPanel.value?.refresh() },
})

/* V0652 (ag): the thread never goes stale silently. The tab coming back, the window's focus and the socket coming back
   catch it up from its last seq (a read of the newest page, merged by seq: nothing twice; a gap reloads the page);
   while the socket is down it long-polls /chat/sync (wait 25 s) instead of going quiet. The header says which:
   live, catching up, offline. His report (seq 297): a message stored and readable reached his open thread only after
   a reload. */
let syncCursor: string | null = null
function nearBottom(): boolean {
  const el = scrollEl.value
  return !el || el.scrollHeight - el.scrollTop - el.clientHeight < 80
}
async function catchUpThread() {
  const id = convId.value
  if (!id || !token.value) return
  const r = await chatApi.getMessages(token.value, id, undefined, 40, joinConfirmed.value)
  if (id !== convId.value || !Array.isArray(r?.messages)) return
  const merged = mergeBySeq(messages.value as any, r.messages)
  if (merged.gap) { await load(); return }
  if (!merged.added) {
    if (merged.updated) messages.value = merged.messages as any     // V0652 (aa): a card moved while away
    return
  }
  const atEnd = nearBottom()
  messages.value = merged.messages
  lastSeq.value = Math.max(lastSeq.value, Number(r.last_seq || 0))
  // V0652 (y): any approval card in what came back, not only the newest message (a decided card under later messages)
  if (r.messages.some((m: any) => touchesApprovals(m))) void approvalsPanel.value?.refresh()
  if (lastSeq.value > 0) void chatApi.markRead(token.value, id, lastSeq.value).catch(() => {})
  if (atEnd && !anchor?.active()) { await nextTick(); scrollBottom() }   // V0654: below a held NEW line it waits
}
async function longPollOnce() {
  const id = convId.value
  if (!token.value) { await new Promise((res) => setTimeout(res, 5000)); return }
  const last: any = messages.value[messages.value.length - 1]
  const r = await chatApi.sync(token.value, syncCursor ? { cursor: syncCursor, wait: 25 }
    : { since: last?.created_at || undefined, wait: 25 })
  if (r?.next_cursor) syncCursor = String(r.next_cursor)
  for (const m of (r?.messages || [])) if (m?.conversation_id === id) ingest(m)
  // V0652 (aa): the cards updated in place since the cursor (the lane rides the cursor)
  const ups = (Array.isArray(r?.updates) ? r.updates : []).filter((u: any) => u?.conversation_id === id)
  if (ups.length) {
    const a = applyCardUpdates(messages.value as any, ups)
    if (a.changed) messages.value = a.messages as any
  }
}
// V0652 (y): the panel answered a late press (decided on another device): this screen missed the decision, likely its
// card too; catch the thread up so the request card reads the decision (best effort, the panel already said it)
function onApprovalsLate() { void catchUpThread().catch(() => {}) }
const liveCatch = useThreadCatchUp({ connected: chatStream?.isConnected ?? ref(false), catchUp: catchUpThread, longPollOnce })
const liveWord = computed(() => liveCatch.state.value === 'live' ? t('ourstate.thread.live', 'live')
  : liveCatch.state.value === 'catching_up' ? t('ourstate.thread.catchingUp', 'catching up')
  : t('ourstate.thread.offline', 'offline'))

/* V0652 (ag): a thread opens at the first message you have not read, under a NEW line (his Pocket report, seq 313:
   "it starts from the whole top of the loaded messages and not at last unread message"); with nothing new it opens at
   the end, as before. */
const unreadFromSeq = ref<number | null>(null)
const unreadCount = ref(0)
function scrollToUnread() {
  const sc = scrollEl.value
  const el = sc?.querySelector('[data-testid="ost-unread-line"]') as HTMLElement | null
  if (!sc || !el) { scrollBottom(); return }
  sc.scrollTop += el.getBoundingClientRect().top - sc.getBoundingClientRect().top - 8
}
/* V0654 (session-lead, the sessions' room seq 937-949; check 140 of V0653's console proof): the open's one scroll to the
   NEW line is held for ANCHOR_MS while the thread settles (the pane's width as the list beside it folds or unfolds,
   fonts, cards, the approvals pinned above), and the reader's own first move anywhere in the thread ends it (see
   services/chat/unreadAnchor.ts). While it holds, a message coming in stays below the line: the reader has not reached
   the end. A send is a move (a press or a key in the thread), so the reader's own message still takes them there. */
let anchor: Anchor | null = null
function endAnchor() { anchor?.stop(); anchor = null }
function holdAnchor() {
  endAnchor()
  if (scrollEl.value) anchor = keepAnchored(scrollEl.value, scrollToUnread, ANCHOR_MS, rootEl.value || scrollEl.value)
}

function ingest(m: any) {
  if (!m || messages.value.some(x => x.id === m.id)) return
  if (touchesApprovals(m)) void approvalsPanel.value?.refresh()
  messages.value = [...messages.value, m].sort((a, b) => a.seq - b.seq)
  lastSeq.value = Math.max(lastSeq.value, Number(m.seq || 0))
  void chatApi.markRead(token.value, convId.value, lastSeq.value).catch(() => {})
  if (!anchor?.active()) void nextTick().then(scrollBottom)   // V0654: below a held NEW line it waits
}

function scrollBottom() { const el = scrollEl.value; if (el) el.scrollTop = el.scrollHeight }

/* ── rendering helpers ── */
const myDids = computed(() => new Set(credAgents.value.map(a => a.did?.toLowerCase()).filter(Boolean)))
/* ── V0652 (x): what names the viewer, what waits on them, the times ── */
const myKey = computed<string | null>(() => {
  const u: any = (auth as any).user || {}
  const id = u.developer_id ?? u.id
  return id != null && id !== '' ? `dev:${id}` : null
})
/** The viewer's own names, held in one computed so every message body gets the SAME array while one types (seq 378). */
const myNames = computed<string[]>(() => {
  const u: any = (auth as any).user || {}
  return [u.handle, u.name].filter((x: any) => typeof x === 'string' && x.length > 0)
})
/** Names the viewer, or asks something of the room (an approval or a choice): never the viewer's own message. */
function forMe(m: any): boolean {
  return !isMine(m) && m?.kind !== 'system' && (namesViewer(m, myKey.value) || isAsk(m))
}
const forMeOnly = ref(false)
const forMeCount = computed(() => messages.value.filter((m: any) => forMe(m)).length)
/* V0652 (ac): threads. Replies fold under the message they answer and an order's messages into its thread, drawn where
   the thread's latest message is; "For me" shows what is for you, unfolded. */
const openThreads = ref(new Set<string>())
/* a thread that holds something new for you opens by itself (seq 419); one folded by hand stays folded over what it
   held then, its newest seq kept, and a newer message for you opens it again (seq 425) */
const closedThreads = ref(new Map<string, number>())
const readFloor = ref(0)
const folded = computed(() => (forMeOnly.value ? null
  : foldThreads(messages.value as any, { expanded: openThreads.value, collapsed: closedThreads.value,
                                         lastReadSeq: readFloor.value,
                                         isMine: (m: any) => isMine(m), forMe: (m: any) => forMe(m) })))
const bars = computed<Record<string, ThreadBar>>(() => folded.value?.bars ?? {})
const inThread = computed<Set<string>>(() => folded.value?.inThread ?? new Set())
const shownMessages = computed<any[]>(() => (forMeOnly.value ? messages.value.filter((m: any) => forMe(m))
  : (folded.value?.list as any[]) ?? messages.value))
function toggleThread(b: ThreadBar) {
  const open = new Set(openThreads.value)
  const closed = new Map(closedThreads.value)
  if (b.expanded) { open.delete(b.key); closed.set(b.key, Number(b.last?.seq) || 0) } else { open.add(b.key); closed.delete(b.key) }
  openThreads.value = open
  closedThreads.value = closed
}
function threadWord(b: ThreadBar): string {
  if (b.kind === 'order') return b.count === 1
    ? tp('ourstate.thread.threadOrderOne', '1 more about {id}', { id: shortOrder(b.orderId) })
    : tp('ourstate.thread.threadOrder', '{n} more about {id}', { n: b.count, id: shortOrder(b.orderId) })
  return b.count === 1 ? t('ourstate.thread.threadReplyOne', '1 reply') : tp('ourstate.thread.threadReplies', '{n} replies', { n: b.count })
}
function shortOrder(id: string | null): string { return id ? `${id.slice(0, 12)}…` : '' }
function speakerName(m: any): string {
  if (!m) return ''
  if (m.sender_ptype === 'system') return railLabel(m.sender_id)
  if (m.sender_name) return String(m.sender_name)
  // a name the read did not carry: never a whole DID in a one-line bar, its tail (DIDs are the address, names are not)
  return m.sender_ptype === 'developer' ? `dev ${m.sender_id}` : `…${String(m.sender_id || '').slice(-8)}`
}
/* where the NEW line goes on the list as drawn: the first new message, or the first thread that holds one */
const unreadLineId = computed<string | null>(() => {
  if (unreadFromSeq.value == null) return null
  for (const m of shownMessages.value) {
    if (bars.value[m.id]?.unread) return m.id
    if (Number(m.seq) >= Number(unreadFromSeq.value) && !folded.value?.rootOf[m.id]) return m.id
    if (Number(m.seq) >= Number(unreadFromSeq.value) && inThread.value.has(m.id)) return m.id
  }
  return null
})
/* V0652 (ac): Reply */
const replyTo = ref<{ id: string; who: string; what: string } | null>(null)
function canReplyTo(m: any): boolean {
  return !!m?.id && !m.deleted && m.kind !== 'system' && !(room.value && !roomComposer.value.canPost) && myState.value !== 'pending'
}
function startReply(m: any) {
  const what = m.kind === 'card' ? String(m.card?.data?.title || m.card?.type || '') : String(m.body || '')
  replyTo.value = { id: String(m.id), who: speakerName(m), what: what.length > 60 ? `${what.slice(0, 59)}…` : what }
  void nextTick(() => inputEl.value?.focus())
}
/* V0652 (ac): the room's status board as the registry now has it (the reader's own can_edit and editors kept) */
function onBoardUpdate(b: any) {
  if (!room.value || !b) return
  room.value = { ...room.value, board: { ...(room.value.board || {}), ...b } }
}
watch(forMeCount, (n) => { if (!n) forMeOnly.value = false })
const fullTimeId = ref<string | null>(null)
function toggleFullTime(id: string) { fullTimeId.value = fullTimeId.value === id ? null : id }

function isMine(m: any): boolean {
  if (m.sender_ptype === 'developer') {
    const u: any = (auth as any).user || {}
    return String(m.sender_id) === String(u.developer_id ?? '') || String(m.sender_id) === String(u.id ?? '')
  }
  return myDids.value.has(String(m.sender_id || '').toLowerCase())
}
function speakerChanged(i: number): boolean {
  const list = shownMessages.value   // V0652 (x): the list on screen (the room, or what is for me)
  const m = list[i]
  if (!m || m.kind === 'system') return false
  // Anchor on the last NON-system message: a ping between two texts must not
  // eat the next speaker's author chip (battery 10a caught exactly that).
  let j = i - 1
  while (j >= 0 && list[j]?.kind === 'system') j--
  const prev = list[j]
  if (!prev) return true
  return prev.sender_ptype !== m.sender_ptype || String(prev.sender_id) !== String(m.sender_id)
}
const isMeAction = (m: any) => m.kind === 'text' && typeof m.body === 'string' && m.body.startsWith('/me ')

/* ── speaker chip ── */
// CORE speaker truth: dm threads speak as YOU (the developer); agent threads
// run their calls as the acting LOCAL agent (the payer) and the chip names it.
// Mixed-speaker dm arrives with OURSTATE-2 — the chip does not offer what the
// auth model would refuse (strategy §3).
const speakerIsAgent = computed(() => isAgentThread.value || !!speakerDid.value)
const speakerLabel = computed(() => {
  if (isAgentThread.value) {
    const a: any = (auth as any).activeAgent
    if (a?.name || a?.did) return a.name || a.did
    const local = credAgents.value.find(x => !x.registry_url || x.registry_url.startsWith(location.origin))
    return local?.name || local?.did || t('ourstate.thread.speakerYou', 'You')
  }
  if (speakerDid.value) {
    const act: any = (auth as any).activeAgent
    if (act?.did === speakerDid.value && act?.name) return act.name
    const a = credAgents.value.find(x => x.did === speakerDid.value)
    return a?.name || speakerDid.value
  }
  return t('ourstate.thread.speakerYou', 'You')
})
const servicePrice = ref<string | null>(null)
async function loadServicePrice() {
  servicePrice.value = null
  if (!isAgentThread.value || !counterpartyDid.value) return
  const id = convId.value, target = counterpartyDid.value
  try {
    const okAgent = await ensureActingAgent()
    const jwt = okAgent ? (auth as any).agentToken : null
    if (!jwt) return
    const r = await fetch(`/api/v1/a2a-payment/quote?target_agent_did=${encodeURIComponent(target)}`,
                          { headers: { Authorization: `Bearer ${jwt}` } })
    if (!r.ok) return
    const q = await r.json()
    if (id !== convId.value || target !== counterpartyDid.value) return   // the price of another thread's agent
    if (!q?.payment_required) { servicePrice.value = null; return }
    // The buyer's own currency, which is what they will actually part with.
    if (q.your_amount && q.your_currency) servicePrice.value = `${q.your_amount} ${q.your_currency}`
    else if (q.price && q.price_currency) servicePrice.value = `${q.price} ${q.price_currency}`
  } catch { /* unknown stays unknown */ }
}

/** The composer says what it will DO with what you type. */
const composerPlaceholder = computed(() => {
  if (isSupportThread.value) return t('ourstate.support.placeholder', 'Reply to support…')
  if (assistOn.value) return t('ourstate.assist.placeholder', 'Ask your assistant…')   // the amber chip names who
  if (!isAgentThread.value) return t('ourstate.thread.placeholder', 'Message — / for commands')
  const who = counterparty.value?.name || t('ourstate.thread.thisAgent', 'this agent')
  const price = servicePrice.value
  return price
    ? tp('ourstate.thread.askPricedPh', 'Ask {who} — {price} per answer',
         { who, price })
    : tp('ourstate.thread.askPh', 'Ask {who}…', { who })
})

const speakerTitle = computed(() =>
  t('ourstate.thread.speakerTitleThread', 'Who your next message goes out as. You, unless you choose an agent for this thread; each message keeps its author forever.'))

/* ── composer ── */
const input = ref('')
const hint = ref('')
const hintSendAsText = ref(false)
const hintNeedsAgent = computed(() => !!hint.value && !credAgents.value.length && !sealedLocked.value)
const sending = ref(false)
const serviceBusy = ref(false)
/** The composer context, built ONCE — the completion filter, the /help sheet
 *  and `parseComposer` must all be told the same thing about this thread. */
const composerCtx = computed(() => ({
  actingCurrency: actingCurrencyLabel.value || null,
  agentThread: isAgentThread.value,
  /* §CHATCOHERE D9 (2026-09-01) — this key was never set, so `commandGroups()`
     read `ctx.wallet === undefined`, dimmed `/balance` and printed "not here —
     this surface cannot read a wallet yet" in /help. §OURCHATBAL implemented
     `showBalance()` in THIS FILE on 2026-08-28: the help sheet and the handler
     disagreed about the same command, and the help sheet was the wrong one.
     The predicate is `showBalance()`'s OWN first line, so the offer and the
     handler cannot drift apart again. */
  wallet: !!walletDid.value,
  room: room.value ? { isOperator: !!room.value.my_is_operator } : null,
}))
const completionsList = computed(() => completions(input.value, composerCtx.value))
const sendDisabled = computed(() => sending.value || serviceBusy.value || serviceInflight.value ||
  !input.value.trim() || myState.value === 'left')

/* ── §OURSTATE-7 B — /help as a grouped, colour-coded sheet ──
   It was `SLASH_COMMANDS.map(c => c.usage).join(' · ')` dropped into the
   one-line hint: 23 commands on one line, no structure, no indication which of
   them work HERE. The groups come from `commandGroups()`, so the colours are a
   summary of declared metadata rather than a second opinion about it. */
const helpOpen = ref(false)
const helpGroups = computed(() => commandGroups(composerCtx.value))
/* §CHATCOHERE A4 — which all-unavailable groups the reader has chosen to open.
   A Set, reset every time the sheet opens, because "show me the room commands"
   is a question about THIS look, not a preference worth persisting. */
const helpExpanded = ref<Set<string>>(new Set())
/** True when NOT ONE command in the group applies in this thread. A group with
 *  even one usable command is never collapsed — the point is to fold away what
 *  is wholly irrelevant, never to hide something that works. */
function helpGroupOff(g: { items: Array<{ unavailable: string | null }> }): boolean {
  return g.items.length > 0 && g.items.every(c => !!c.unavailable)
}
const HELP_GROUP_LABEL: Record<string, [string, string]> = {
  any:   ['ourstate.help.groupAny', 'Always here'],
  agent: ['ourstate.help.groupAgent', 'This agent'],
  wallet: ['ourstate.help.groupWallet', 'Your wallet'],
  room:  ['ourstate.help.groupRoom', 'This room'],
  op:    ['ourstate.help.groupOp', 'Room operators'],
}
const HELP_GROUP_RULE: Record<string, [string, string]> = {
  any:   ['ourstate.help.ruleAny', 'Every thread, every time.'],
  agent: ['ourstate.help.ruleAgent', 'Needs a service agent on the other side — and these spend money.'],
  wallet: ['ourstate.help.ruleWallet', 'Needs a wallet this surface can read.'],
  room:  ['ourstate.help.ruleRoom', 'Organization rooms only.'],
  op:    ['ourstate.help.ruleOp', 'Organization rooms, and only for an owner or admin.'],
}
const HELP_UNAVAILABLE: Record<string, [string, string]> = {
  'needs-agent':  ['ourstate.help.whyNeedsAgent', 'not here — no service agent in this thread'],
  'needs-wallet': ['ourstate.help.whyNeedsWallet', 'not here — this surface cannot read a wallet yet'],
  'not-a-room':   ['ourstate.help.whyNotARoom', 'not here — this is not an organization room'],
  'not-operator': ['ourstate.help.whyNotOperator', 'not you — needs an org owner or admin'],
}
function helpLabel(g: string) { const [k, f] = HELP_GROUP_LABEL[g] || ['', g]; return t(k, f) }
function helpRule(g: string) { const [k, f] = HELP_GROUP_RULE[g] || ['', '']; return t(k, f) }
function helpWhy(r: string) { const [k, f] = HELP_UNAVAILABLE[r] || ['', r]; return t(k, f) }
/** Tapping a usable command fills the composer with it; tapping a dimmed one
 *  does nothing, because its reason is already on screen. */
function helpPick(cmd: string, unavailable: string | null) {
  if (unavailable) return
  input.value = cmd + ' '
  helpOpen.value = false
  inputEl.value?.focus()
}

/* ── §OURSTATE-7 C — name completion for /card and /find ──
   The names come from the EXISTING discover rail — the same index the find
   sheet and the day-one cast read — so an agent's identity and price cannot
   disagree between surfaces. What discovery does NOT have is a local copy, and
   inventing one here would be a second source of truth about price. Debounced,
   cached per thread, and a failed read SAYS SO rather than rendering empty. */
const agentSuggest = ref<any[]>([])
const agentSuggestBusy = ref(false)
const agentSuggestErr = ref('')
const suggestCache = new Map<string, any[]>()
let suggestTimer: any = null
let suggestSeq = 0

const argHint = computed(() => argCompletions(input.value, composerCtx.value))

watch(argHint, spec => {
  if (suggestTimer) { clearTimeout(suggestTimer); suggestTimer = null }
  if (!spec) { agentSuggest.value = []; agentSuggestErr.value = ''; agentSuggestBusy.value = false; return }
  const q = spec.query
  const cached = suggestCache.get(q)
  if (cached) { agentSuggest.value = cached; agentSuggestErr.value = ''; agentSuggestBusy.value = false; return }
  agentSuggestBusy.value = true
  agentSuggestErr.value = ''
  suggestTimer = setTimeout(() => void fetchSuggest(q), 250)
})

async function fetchSuggest(q: string) {
  // A stale answer must never overwrite a fresh one: the reply that lands last
  // is not necessarily the one for what is on screen now.
  const mine = ++suggestSeq
  try {
    const r = await discoveryService.discover({ q, limit: 6, sort: 'proven' } as any)
    const rows = (r.results || []).filter((a: any) => a?.did)
    suggestCache.set(q, rows)
    if (mine !== suggestSeq) return
    agentSuggest.value = rows
    agentSuggestErr.value = ''
  } catch {
    if (mine !== suggestSeq) return
    agentSuggest.value = []
    agentSuggestErr.value = t('ourstate.card.discoverDown', 'Could not reach discovery just now.')
  } finally { if (mine === suggestSeq) agentSuggestBusy.value = false }
}

function suggestPrice(a: any): string {
  const p = a?.pricing
  if (p?.payment_required && p?.base_rate) return `${p.base_rate} ${p.currency || ''}`.trim()
  return t('ourstate.card.free', 'free')
}

/** Post an agent.card. Sharing a card moves nothing and names nobody's money —
 *  it is a message, so a deliberate pick from the list IS the send. */
async function shareAgentCard(did: string, name?: string) {
  if (!did) return
  sending.value = true
  try {
    const r = await chatApi.postMessage(speakingToken.value, convId.value,
      { kind: 'card', card: buildAgentCard(did, name), client_ref: uuid() })
    ingest(r.message)
    input.value = ''
    agentSuggest.value = []
  } catch (e: any) { hint.value = e?.detail || String(e) } finally { sending.value = false }
}

/** §OURCHAT-ORG — `/stock <ticker>`: share a listing that ALREADY trades here.
 *
 *  The symbol is resolved against the venue rather than trusted from the
 *  composer, for the same reason `/card` resolves a name: a card that can name
 *  a listing which does not exist is a card that can point somebody at nothing.
 *  A miss refuses BY NAME. What gets posted is a POINTER — symbol, the venue's
 *  own display name, and an indicative last price WITH its currency; never a
 *  side and never a size, because those are the person's to choose in the
 *  ticket. */
/** §SHOWCASESTOCKS — what trades right now, with LIVE prices, across the whole
 *  federation rather than only this registry. A read: it posts nothing. */
const stockList = ref<string[]>([])
const stockListOpen = ref(false)

/* §OURCHATBAL — `/balance` was in the SHARED command table with a help gloss and
   an alias (`/bal`), so OurChat offered it in autocomplete and listed it under
   /help — and the send switch had no `case 'balance'` and no `default:`, so
   pressing enter did nothing at all. The showcase chat grew a handler in
   §SHOWCASEBAL; this surface never did. Measured 2026-08-28: it is the ONLY
   command of the 24 that is handled on one surface and dead on the other.

   ⚠ It reports the ACTING AGENT's position, not a developer-wide total. The
   fleet aggregate (`getTegSummary().total_balance`) sums registries that do not
   share a currency and is still labelled with ONE — a known open defect
   (§FOREIGNACT). With no agent acting we say so, rather than showing a sum whose
   unit we would have to guess.

   ⚠ `AgentBalance` carries NO currency field, so the unit comes from
   `useActingContext().actingCurrencyLabel` — the §FOREIGNACT composable, which
   reads the very field the api client routes the request on, so the label and
   the money cannot disagree. When it has not resolved yet the number is printed
   with NO unit: an empty unit, never the viewer's, because that fallback IS the
   bug §FOREIGNACT was opened for. */
const balanceOpen = ref(false)
const balanceBusy = ref(false)
const balanceLines = ref<string[]>([])
const balanceNote = ref('')

async function showBalance() {
  input.value = ''
  balanceLines.value = []; balanceNote.value = ''
  balanceOpen.value = true; balanceBusy.value = true
  try {
    const act: any = (auth as any).activeAgent
    const did = walletDid.value
    if (!did) {
      balanceNote.value = t('ourstate.balance.noAgent',
        'No agent is acting, so there is no single purse to report. Pick one in the header.')
      return
    }
    const raw: any = await developerApi.getAgentBalancesBatch([did])
    const b = (raw?.balances || raw || {})[did] || {}
    const liquid = b.liquid_balance ?? b.balance
    const ccy = String(actingCurrencyLabel.value || '')   // empty, never the viewer's
    if (liquid === undefined || liquid === null) {
      balanceNote.value = t('ourstate.balance.unknown',
        'The ledger did not answer just now — no number rather than a guessed one.')
      return
    }
    balanceLines.value.push(
      `${t('ourstate.balance.hold', 'you hold')} ${displayAmount(String(liquid)) || String(liquid)} ${ccy}`.trim())
    const staked = b.staked_balance ?? b.staked
    if (staked !== undefined && staked !== null && Number(staked) > 0) {
      balanceLines.value.push(
        `${t('ourstate.balance.staked', 'locked')} ${trim(String(staked)) ?? String(staked)} ${ccy}`.trim())
    }
    balanceNote.value = tp('ourstate.balance.whose',
      'This is {who} — the agent this thread sends as. Its registry decides the currency.',
      { who: act?.name || speakerLabel.value || did })
  } catch (e: any) {
    balanceNote.value = t('ourstate.balance.unknown',
      'The ledger did not answer just now — no number rather than a guessed one.')
  } finally { balanceBusy.value = false }
}
async function showStockList(query: string | null) {
  sending.value = true
  try {
    const [netR, locR, fxR, tkR] = await Promise.all([
      exchangeService.networkListings().catch(() => null),
      exchangeService.listings().catch(() => null),
      exchangeService.fxRates().catch(() => null),
      // The federated catalog has no `stats`, so without this every foreign
      // listing shows its founding float — the SYBIL 5.0-vs-105.1 bug.
      exchangeService.federationTickers().catch(() => null),
    ])
    // The federated catalog carries no `stats`, so local rows are re-read from
    // the local venue, where the live book actually is.
    const locals = new Map((((locR as any)?.listings || []) as any[]).map(
      (x: any) => [String(x.symbol).toUpperCase(), normalizeListing(x)]))
    let rows = ((((netR as any)?.listings || (locR as any)?.listings || []) as any[]))
      .map(normalizeListing)
      .map((r: any) => locals.get(r.symbol) ?? r)
    const q = String(query || '').trim().toUpperCase()
    if (q) rows = rows.filter((r: any) => r.symbol.includes(q) || r.displayName.toUpperCase().includes(q))
    rows = mergeTickers(rows, tkR)
    rows.sort((a: any, b: any) => (a.isLocal === b.isLocal ? a.symbol.localeCompare(b.symbol) : (a.isLocal ? -1 : 1)))
    stockList.value = rows.map((r: any) => priceLine(r, actingCurrencyLabel.value || null, fxR))
    stockListOpen.value = true
    input.value = ''
  } catch (e: any) {
    hint.value = e?.detail || e?.message || t('ourstate.card.venueDown', 'Could not reach the market just now.')
  } finally { sending.value = false }
}

async function resolveAndShareListing(symbol: string) {
  const sym = String(symbol || '').trim().toUpperCase()
  if (!sym) {
    hint.value = t('ourstate.card.needSymbol', '/listing needs a ticker: /listing SMKD')
    return
  }
  sending.value = true
  try {
    const r = await exchangeService.listings()
    const row = (r.listings || []).find((l: any) => String(l.symbol || '').toUpperCase() === sym)
    if (!row) {
      hint.value = tp('ourstate.card.noListing', 'No listing called “{s}” trades on this registry.', { s: sym })
      return
    }
    // A delisted or halted symbol is still a real record, and saying which it
    // is beats posting a door that opens onto a suspended book.
    const card: any = {
      v: 1, type: 'exchange.listing',
      data: { symbol: String(row.symbol).toUpperCase(),
              display_name: row.display_name || '',
              status: row.status || '' },
    }
    // Amount and unit travel together or not at all — the §FOREIGNACT rule,
    // and this card is read across frames more often than not.
    // 🔴 THE SAME INVENTED FIELD AS THE LANDING SHOWCASE, and it shipped HERE
    // first (§OURCHAT-ORG): `last_price` does not exist on a listings row — the
    // live numbers are under `stats`. This card has shown the FOUNDING float
    // price for every symbol since it landed (SMKD 2.5 while the book traded at
    // 51). Foreign rows additionally get their live price from the tickers rail,
    // since the federated catalog carries no stats at all.
    const tk = await exchangeService.federationTickers().catch(() => null)
    const [nr] = mergeTickers([normalizeListing(row)], tk)
    const eff = effectivePrice(nr)
    if (eff.value && nr.currency) { card.data.last_price = eff.value; card.data.currency = nr.currency }
    const res = await chatApi.postMessage(speakingToken.value, convId.value,
      { kind: 'card', card, client_ref: uuid() })
    ingest(res.message)
    input.value = ''
  } catch (e: any) {
    hint.value = e?.detail || e?.message || t('ourstate.card.venueDown', 'Could not reach the market just now.')
  } finally { sending.value = false }
}

/** `/card <query>` + send. One match posts it; none refuses BY NAME; several
 *  refuse and show the list — a picker that guesses is not a picker. */
async function resolveAndShareCard(query: string) {
  const q = query.trim()
  if (!q) {
    hint.value = t('ourstate.card.needName', '/card needs a name — start typing and pick one.')
    return
  }
  if (q.toLowerCase().startsWith('did:')) return shareAgentCard(q)
  let rows = suggestCache.get(q)
  if (!rows) {
    sending.value = true
    try {
      const r = await discoveryService.discover({ q, limit: 6, sort: 'proven' } as any)
      rows = (r.results || []).filter((a: any) => a?.did)
      suggestCache.set(q, rows)
    } catch {
      hint.value = t('ourstate.card.discoverDown', 'Could not reach discovery just now.')
      return
    } finally { sending.value = false }
  }
  const exact = rows.filter((a: any) => String(a.name || '').toLowerCase() === q.toLowerCase())
  const pick = exact.length === 1 ? exact : rows
  if (!pick.length) {
    hint.value = tp('ourstate.card.noMatch', 'No agent matches “{q}”.', { q })
    return
  }
  if (pick.length > 1) {
    agentSuggest.value = pick
    hint.value = tp('ourstate.card.ambiguous', '{n} agents match “{q}” — pick one.',
                    { n: String(pick.length), q })
    return
  }
  await shareAgentCard(pick[0].did, pick[0].name)
}

const draftKey = computed(() => `os_draft_${convId.value}`)
watch(input, v => { try { v ? localStorage.setItem(draftKey.value, v) : localStorage.removeItem(draftKey.value) } catch { /* private mode */ } })

const uuid = () => (crypto as any).randomUUID ? crypto.randomUUID() :
  'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => { const r = Math.random() * 16 | 0; return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16) })

/* offline queue: replays through client_ref idempotency — a replayed double
   is refused by the schema, not by luck. */
const OUTBOX_KEY = 'os_outbox'
function outboxPush(item: any) {
  try {
    const q = JSON.parse(localStorage.getItem(OUTBOX_KEY) || '[]')
    q.push(item); localStorage.setItem(OUTBOX_KEY, JSON.stringify(q))
  } catch { /* full/private */ }
}
async function outboxReplay() {
  let q: any[] = []
  try { q = JSON.parse(localStorage.getItem(OUTBOX_KEY) || '[]') } catch { q = [] }
  if (!Array.isArray(q) || !q.length) return
  const rest: any[] = []
  for (const item of q) {
    try { await chatApi.postMessage(token.value, item.conversationId, item.payload) }
    catch (e: any) { if (!e?.status) rest.push(item) /* network-down: keep; a 4xx is consumed */ }
  }
  try { localStorage.setItem(OUTBOX_KEY, JSON.stringify(rest)) } catch { /* ignore */ }
  if (rest.length < q.length) void load()
}

async function postText(body: string) {
  const payload: { kind: 'text'; body: string; client_ref: string; reply_to?: string } = { kind: 'text' as const, body, client_ref: uuid() }
  if (replyTo.value) payload.reply_to = replyTo.value.id      // V0652 (ac): the reply folds under the message it answers
  sending.value = true
  try {
    const r = await chatApi.postMessage(speakingToken.value, convId.value, payload)
    if (r?.my_state) myState.value = r.my_state
    ingest(r.message)
    replyTo.value = null
    // your own message never vanishes into a fold: the thread it joined opens
    const root = folded.value?.rootOf[String(r?.message?.id || '')]
    if (root && bars.value[root] && !bars.value[root].expanded) toggleThread(bars.value[root])
    input.value = ''
  } catch (e: any) {
    if (!e?.status) { outboxPush({ conversationId: convId.value, payload }); input.value = ''; hint.value = t('ourstate.thread.queued', 'Offline — queued, sends when you are back.') }
    else hint.value = e?.detail || String(e)
  } finally { sending.value = false }
}

async function sendPlainAnyway() { hint.value = ''; hintSendAsText.value = false; await postText(input.value.trim()) }

/* PocketSend prefill (the /pay door + pay.request taps) */
const sendEver = ref(false)
const sendOpen = ref(false)
const sendPrefill = ref<{ to?: string; amount?: string; memo?: string }>({})
function openPayDoor(p: { amount: string; currency: string; memo: string }) {
  sendPrefill.value = { to: counterpartyDid.value || undefined, amount: p.amount, memo: p.memo }
  sendEver.value = true; sendOpen.value = true
}

/* §OURSTATE-5f — an applet's ONE action, consumed here. Every branch opens an
   EXISTING door with the collected values filled in; none of them sends,
   pays, or commits anything. The applet asks, the door confirms, the human
   presses — the fill-never-fire rule the composer and the voice grammar
   already live under. An action this app does not have opens nothing and says
   so, rather than failing silently. */
function openAppletDoor(p: { kind: string; values: Record<string, any>
                             amount: string | null; currency: string | null
                             did: string | null }) {
  const summary = Object.entries(p.values || {})
    .filter(([, v]) => v !== '' && v != null && v !== false)
    .map(([k, v]) => `${k}: ${v}`).join(', ')
  switch (p.kind) {
    case 'open_pay':
      sendPrefill.value = {
        to: p.did || counterpartyDid.value || undefined,
        amount: p.amount || undefined,
        memo: summary || undefined,
      }
      sendEver.value = true; sendOpen.value = true
      return
    case 'open_buy':
      if (!p.did && !counterpartyDid.value) {
        hint.value = t('ourstate.card.appletNoTarget', 'That card names no agent to buy from.')
        return
      }
      detailDid.value = p.did || counterpartyDid.value || ''
      detailEver.value = true; detailOpen.value = true
      return
    case 'open_work':
      return openWorkPicker()
    case 'open_trade': {
      // The applet may name the symbol in a field; the card's own `amount`
      // is not one, because a listing pointer carries no size.
      const sym = String(p.values?.symbol ?? p.values?.ticker ?? '').trim()
      if (!sym) {
        hint.value = t('ourstate.card.appletNoSymbol', 'That card names no symbol to trade.')
        return
      }
      return openTradeDoor({ symbol: sym })
    }
    case 'open_reply':
      // A DRAFT in the composer, never a sent message.
      input.value = summary || input.value
      return
    default:
      hint.value = t('ourstate.card.appletUnknownDoor',
                     'That card asks for something this app does not offer.')
  }
}

/* §OURSTATE-6 — a payment made from a thread LEAVES something in the thread.
   Before this, the sheet closed and the conversation carried no trace: the
   money moved and the record of it lived only in your activity feed. The card
   is posted best-effort — a receipt that fails to post must never look like a
   payment that failed. */
async function onSent(r?: any) {
  sendOpen.value = false
  const receipt = typeof r === 'string' ? { ref: r } : (r || {})
  if (!receipt.ref && !receipt.amount) return
  try {
    const card = buildPayReceipt(receipt)
    const m = await chatApi.postMessage(token.value, convId.value,
      { kind: 'card', card, client_ref: `receipt-${receipt.ref || uuid()}` })
    ingest(m.message || m)
  } catch {
    // Say it plainly rather than silently: the money moved, the note did not.
    hint.value = t('ourstate.thread.receiptFailed',
      'Paid — but the receipt card could not be posted to this thread.')
  }
}

/* The correction affordance, honestly named. A completed transfer is FINAL on
   this network (rule 10 forbids balance surgery), so there is no undo to
   build: what exists is a request, and it rides the pay.request card that
   already means "please send me this". */
function askBack(p: { amount: string; currency: string; txId: string | null }) {
  const memo = p.txId
    ? tp('ourstate.thread.askBackMemo', 'returning payment {ref}', { ref: p.txId.slice(0, 12) })
    : t('ourstate.thread.askBackMemoBare', 'returning a payment')
  input.value = ''
  askBackCard.value = { amount: p.amount, currency: p.currency, memo }
  askBackOpen.value = true
}

const askBackOpen = ref(false)

/** §DEALTHREADS — a system sender's human label (a rail is machinery, not a person). */
function railLabel(senderId: any): string {
  const id = String(senderId || '')
  if (id === 'room-assistant') return t('ourstate.thread.railAssistant', '@assistant')
  if (id === 'deal-rail') return t('ourstate.thread.railContract', 'Contract rail')
  if (id === 'org-ledger') return t('ourstate.thread.railTreasury', 'Treasury')
  if (id.includes('support')) return t('ourstate.thread.railSupport', 'Support')
  if (id === 'guild') return t('ourstate.thread.railGuild', 'Guild')    // V0652 (aa): the Guild's order card
  return t('ourstate.thread.railSystem', 'System')
}

// ── §DEALTHREADS — the proposal composer + the engage confirm ────────────────
const proposeOpen = ref(false)
const proposeBusy = ref(false)
const proposeForm = ref({ title: '', total: '', note: '', supersedes: '' })
const engageConfirm = ref<{ did: string; title: string; total: string | null; currency: string | null; note: string | null } | null>(null)
const engageBusy = ref(false)
const engageErr = ref('')

function openPropose(prefill?: { title: string; total: string | null; note: string | null } | null,
                     supersedes?: string) {
  proposeForm.value = {
    title: prefill?.title || '',
    total: prefill?.total || '',
    note: prefill?.note || '',
    supersedes: supersedes || '',
  }
  proposeOpen.value = true
}

async function submitPropose() {
  if (proposeBusy.value || !proposeForm.value.title.trim()) return
  proposeBusy.value = true
  try {
    const card = buildEngagementProposal({
      title: proposeForm.value.title.trim(),
      total: proposeForm.value.total.trim() || null,
      currency: proposeForm.value.total.trim() ? (actingCurrencyLabel.value || undefined) : null,
      note: proposeForm.value.note.trim() || null,
      supersedes: proposeForm.value.supersedes || null,
    })
    const r = await chatApi.postMessage(token.value, convId.value, { kind: 'card', card, client_ref: uuid() })
    ingest(r.message)
    proposeOpen.value = false
  } catch (e: any) { hint.value = e?.detail || String(e) } finally { proposeBusy.value = false }
}

/** "Use these terms" — the OFFER moment. Prefills the confirm from the card;
 *  the offer goes to the thread's counterparty AGENT, opens/reuses THIS thread
 *  (open_thread), and re-reads everything server-side. */
function openEngageConfirm(p: { title: string; total: string | null; currency: string | null; note: string | null }) {
  if (!counterpartyDid.value) {
    hint.value = t('ourstate.thread.noEngageTarget', 'This thread has no agent counterparty to engage.')
    return
  }
  engageErr.value = ''
  engageConfirm.value = { did: counterpartyDid.value, ...p }
}

async function runEngage() {
  const c = engageConfirm.value
  if (!c || engageBusy.value) return
  engageBusy.value = true
  engageErr.value = ''
  try {
    const body: any = { open_thread: true }
    if (c.total) body.total_amount = Number(c.total)
    if (c.note) body.message = c.note
    await contractsV2Api.engage(c.did, body)
    engageConfirm.value = null
    await load()   // the rail posted the offer card; re-read the thread
  } catch (e: any) {
    engageErr.value = e?.detail || e?.message || String(e)
  } finally { engageBusy.value = false }
}

/** The offer card's Accept — the SAME rail the contract surfaces call, as the
 *  ACTING agent; the rail (not the card) decides whether this viewer may. */
async function acceptDealOffer(p: { contractId: string }) {
  try {
    await contractsV2Api.accept(p.contractId)
    hint.value = t('ourstate.thread.offerAccepted', 'Offer accepted — escrow held. The thread gets the record.')
    await load()
  } catch (e: any) {
    hint.value = e?.detail || e?.message || String(e)
  }
}
const askBackCard = ref<{ amount: string; currency: string; memo: string } | null>(null)

async function sendAskBack() {
  const a = askBackCard.value
  if (!a) return
  askBackOpen.value = false
  try {
    const m = await chatApi.postMessage(token.value, convId.value,
      { kind: 'card', card: buildPayRequest(a.amount, a.currency, a.memo), client_ref: uuid() })
    ingest(m.message || m)
  } catch (e: any) { hint.value = e?.detail || String(e) }
}

/* §OURSTATE-6 — hosting + retention, read from the thread rather than assumed.
   A read FAILURE renders no line at all: silence is honest about not knowing,
   while a default sentence would be a claim we did not verify. */
const hosting = ref<any>(null)
const retentionHours = ref<number | null>(null)

const RETENTION_CHOICES = [
  { h: null, k: 'ourstate.thread.timerOff', d: 'Keep everything' },
  { h: 1, k: 'ourstate.thread.timer1h', d: 'Delete after 1 hour' },
  { h: 24, k: 'ourstate.thread.timer24h', d: 'Delete after 1 day' },
  { h: 168, k: 'ourstate.thread.timer7d', d: 'Delete after 7 days' },
  { h: 720, k: 'ourstate.thread.timer30d', d: 'Delete after 30 days' },
]

const retentionLabel = computed(() => {
  const h = retentionHours.value
  if (!h) return ''
  if (h < 24) return tp('ourstate.thread.timerLabelH', 'messages here disappear after {n}h', { n: String(h) })
  return tp('ourstate.thread.timerLabelD', 'messages here disappear after {n}d',
            { n: String(Math.round(h / 24)) })
})

const timerOpen = ref(false)

/* §OURSTATE-6 — /here. Two different questions wearing one word:
   in a ROOM it is the member sheet the registry keeps (live org roles); in a
   DM it is the two parties. The sheet says WHICH it answered, because "the two
   of you" and "everyone who opened this room" are not the same fact, and a
   room whose member read failed must not render as a room of two. */
/* §OURSTATE-6 — a stored receipt is a SNAPSHOT. `/settle` answers `settling`
   and moves the money in a background task, so a card written at that instant
   says "settling" forever even though the transfer landed seconds later. When
   a thread holds a receipt whose stored word is not terminal, ask the token's
   own rail ONCE per load and hand the live status down. `my-tokens` is scoped
   to the calling agent by construction, so this can only ever read your own.
   A failed read leaves the map empty and the card falls back to its stored
   word — never to a comforting one. */
const liveSettle = ref<Record<string, string>>({})
// V0650 (l): each approval request card's live status, read from the thread itself (a later approval.decided card)
const liveApproval = computed<Record<string, string>>(() => liveApprovalStatus(messages.value, Date.now()))

async function refreshSettlements() {
  const pending = messages.value
    .filter(m => m.kind === 'card' && m.card?.type === 'service.result' &&
                 !['settled', 'failed', 'released'].includes(String(m.card?.data?.settlement_status || '')))
    .map(m => m.card?.refs?.token_id)
    .filter(Boolean) as string[]
  if (!pending.length) return
  try {
    const okAgent = await ensureActingAgent()
    const jwt = okAgent ? (auth as any).agentToken : null
    if (!jwt) return
    const r = await fetch('/api/v1/a2a-payment/my-tokens?limit=200',
                          { headers: { Authorization: `Bearer ${jwt}` } })
    if (!r.ok) return
    const rows = await r.json()
    const next: Record<string, string> = {}
    for (const t of (Array.isArray(rows) ? rows : [])) {
      if (t?.token_id && pending.includes(t.token_id) && t.status) next[t.token_id] = String(t.status)
    }
    liveSettle.value = { ...liveSettle.value, ...next }
  } catch { /* stored word stands; absence is not a verdict */ }
}

const hereOpen = ref(false)
const hereBusy = ref(false)
const hereScope = ref<'room' | 'pair' | 'unreadable'>('pair')
type HereRow = { ptype: 'developer' | 'agent'; pid: string; fallbackName: string; note: string }
const hereRows = ref<HereRow[]>([])

async function openHere() {
  hereOpen.value = true
  hereBusy.value = true
  hereRows.value = []
  try {
    if (kind.value === 'org') {
      const r: any = await chatApi.roomMembers(token.value, convId.value)
      hereScope.value = 'room'
      hereRows.value = (r?.members || []).map((m: any): HereRow => ({
        ptype: m.ptype === 'agent' ? 'agent' : 'developer',
        pid: String(m.agent_did ?? m.developer_id ?? ''),
        fallbackName: String(m.name || ''),
        // LIVE org role, not a stored one — the room reads the roster on every
        // request, so what /here prints is what the registry would enforce.
        note: [m.org_role, m.can_post === false ? t('ourstate.here.muted', 'muted') : '']
                .filter(Boolean).join(' · '),
      })).filter((x: HereRow) => x.pid)
    } else {
      hereScope.value = 'pair'
      const cp = counterparty.value
      const rows: HereRow[] = []
      // YOU: resolved through the same identity mount as every other name, so
      // the flare and the collar render here exactly as they do in the thread.
      const me: any = (auth as any).user || {}
      const myId = me.developer_id ?? me.id
      if (myId != null) {
        rows.push({ ptype: 'developer', pid: String(myId),
                    fallbackName: t('ourstate.here.you', 'You'),
                    note: hosting.value?.registry || '' })
      }
      if (cp) {
        rows.push({ ptype: cp.ptype === 'agent' ? 'agent' : 'developer',
                    pid: String(cp.agent_did ?? cp.developer_id ?? ''),
                    fallbackName: t('ourstate.here.them', 'The other side'),
                    // The thread read does not carry a home for the counterparty,
                    // so this says where the THREAD lives and does not guess at
                    // where they do. An invented origin would be worse than none.
                    note: hosting.value?.registry || '' })
      }
      hereRows.value = rows.filter(r => r.pid)
    }
  } catch {
    // A failed read is its own answer: rendering the pair fallback here would
    // report a room as a two-person thread.
    hereScope.value = 'unreadable'
  } finally { hereBusy.value = false }
}
async function setRetention(h: number | null) {
  timerOpen.value = false
  try {
    const r: any = await chatApi.setRetention(token.value, convId.value, h)
    retentionHours.value = r.retention_hours ?? null
    if (r.system_message) ingest(r.system_message)
    // The bound, stated once, at the moment it is set.
    hint.value = r.note || ''
  } catch (e: any) { hint.value = e?.detail || String(e) }
}

/* AgentDetailModal */
const AgentDetailModal = defineAsyncComponent(() => import('@/components/AgentDetailModal.vue'))
const detailEver = ref(false)
const detailOpen = ref(false)
const detailDid = ref('')
watch(detailOpen, v => { if (v) { detailEver.value = true; detailDid.value = counterpartyDid.value || detailDid.value } })
function openAgentDetail(did: string) { detailDid.value = did; detailEver.value = true; detailOpen.value = true }

/* /audit */
const auditOpen = ref(false)
const auditAuthority = ref<any>(null)

/* An authority read that FAILS renders nothing rather than "cannot commit":
   silence is honest about not knowing, while a denial we did not verify would
   be a claim about someone else's grant. */
async function loadAuditAuthority() {
  auditAuthority.value = null
  try {
    const r: any = await chatApi.conversationAuthority(token.value, convId.value)
    const list = Array.isArray(r?.stand_ins) ? r.stand_ins : []
    auditAuthority.value = list.find((x: any) => x.agent_did === auditDid.value) || null
  } catch { auditAuthority.value = null }
}
const auditDid = ref<string | null>(null)

/* ── §OURSTATE-2: room machinery ─────────────────────────────────────────
   The brain (orgRoomActions) decides what to OFFER; the server re-gates every
   act on the LIVE org role. Destructive acts hold-to-execute. */
const roomCtx = computed(() => room.value ? {
  myOrgRole: room.value.my_org_role ?? null,
  myCanPost: room.value.my_can_post !== false,
  mode: room.value.mode === 'announce' ? 'announce' as const : 'open' as const,
  myState: myState.value,
} : null)
const roomComposer = computed(() =>
  roomCtx.value ? composerCan(roomCtx.value) : { canPost: true, note: '', noteKey: '' })

/** "Commander set messages here to disappear after 24 hours." — the words the
 *  card was always meant to carry. Names WHO, because a timer changes what the
 *  other side keeps and an anonymous change is exactly what would need a name. */
function retentionRowText(m: any): string {
  const who = m.sender_name || t('ourstate.here.them', 'The other side')
  const raw = String(m.body || '')
  if (raw === 'retention.off') {
    return tp('ourstate.thread.rowTimerOff', '{who} turned disappearing messages off — everything is kept.', { who })
  }
  const h = Number(raw.replace('retention.', '').replace('h', ''))
  if (!Number.isFinite(h) || h <= 0) return raw
  return h < 24
    ? tp('ourstate.thread.rowTimerH', '{who} set messages here to disappear after {n}h.', { who, n: String(h) })
    : tp('ourstate.thread.rowTimerD', '{who} set messages here to disappear after {n}d.',
         { who, n: String(Math.round(h / 24)) })
}

function roomRowText(m: any): string {
  // tp keeps the locale's own word order; the brain's template is the fallback.
  const r = systemRowText(m.body, m.card)
  return tp('ourstate.rooms.row.' + r.key, r.template, r.params)
}

/* ── §OURSTATE-7 D — support threads ──
   The ticket decides; the thread shows. Everything below READS ticket state and
   routes writes back through the support rail — there is no support logic here,
   the same way there is no money code in the service-call door. */
const supportTicket = ref<any | null>(null)
const supportErr = ref('')

const SUPPORT_STATUS_WORD: Record<string, [string, string]> = {
  open:        ['ourstate.support.statusOpen', 'open'],
  in_progress: ['ourstate.support.statusProgress', 'being worked on'],
  resolved:    ['ourstate.support.statusResolved', 'resolved'],
  closed:      ['ourstate.support.statusClosed', 'closed'],
}
function supportStatusWord(s: string): string {
  const [k, f] = SUPPORT_STATUS_WORD[s] || ['', s]
  return k ? t(k, f) : s
}

function supportRowText(m: any): string {
  const raw = String(m.body || '').replace('support.', '')
  const who = m.sender_name || t('ourstate.support.desk', 'Support')
  return tp('ourstate.support.rowStatus', '{who} marked this ticket {status}.',
            { who, status: supportStatusWord(raw) })
}

/* §CHATDESK C4 — consent-review state (banner + attach flow). */
const reviewGrants = ref<any[]>([])
const liveReviewGrants = computed(() => reviewGrants.value.filter((g: any) => g.live))
const myRevocableGrants = computed(() =>
  liveReviewGrants.value.filter((g: any) => !!g.granted_by_me))
const attachChoices = ref<any[]>([])
const attachPick = ref('')
const attachBusy = ref(false)
const attachMsg = ref('')

/* §ROOMBRAIN privacy panel — ONE sheet composing what is already true:
   hosting (who holds the bytes), retention, and every DISCLOSED reader.
   A failed grants read shows an honest gap, never an empty "nobody". */
const privacyOpen = ref(false)
const privacyGrantsKnown = ref(true)
async function openPrivacy() {
  privacyOpen.value = true
  try {
    const r = await chatApi.reviewState(token.value, convId.value)
    reviewGrants.value = r?.grants || []
    privacyGrantsKnown.value = true
  } catch { privacyGrantsKnown.value = false }
}
// §FESUITE V0578: the consent banner ("Never covert") vanished over a failed grants read, which told every participant
// that the desk could not read the thread; the check says it failed now (Try again), and a failed refresh keeps the
// banner it showed. The support attach picker said nothing over a failed read of your conversations (an empty list).
const reviewUnknown = ref(false)
const attachFailed = ref(false)
async function loadReviewBanner() {
  try {
    const r = await chatApi.reviewState(token.value, convId.value)
    reviewGrants.value = r?.grants || []
    reviewUnknown.value = false
  } catch { reviewUnknown.value = true }
}
async function loadAttachChoices() {
  if (attachChoices.value.length) return
  try {
    const r = await chatApi.listConversations(token.value)
    attachChoices.value = (r?.conversations || []).filter((c: any) => c.kind !== 'support')
    attachFailed.value = false
  } catch { attachChoices.value = []; attachFailed.value = true }
}
async function grantReview() {
  if (!attachPick.value || !supportTicket.value) return
  attachBusy.value = true; attachMsg.value = ''
  try {
    const r = await chatApi.reviewGrant(token.value, attachPick.value, { ticket_id: supportTicket.value.ticket_id })
    attachMsg.value = r?.created
      ? t('cdr.granted', 'Done — everyone in that conversation can see the desk may review it.')
      : t('cdr.already', 'Already allowed for this ticket.')
    attachPick.value = ''
  } catch (e: any) {
    attachMsg.value = e?.detail || String(e)
  } finally { attachBusy.value = false }
}
async function revokeReview(g: any) {
  try { await chatApi.reviewRevoke(token.value, convId.value, g.grant_id); await loadReviewBanner() }
  catch (e: any) { hint.value = e?.detail || String(e) }
}

async function loadSupport() {
  if (!isSupportThread.value) { supportTicket.value = null; await loadReviewBanner(); return }
  const id = convId.value
  try {
    const ticket = await chatApi.supportState(token.value, id)
    if (id !== convId.value) return
    supportTicket.value = ticket
    supportErr.value = ''
  } catch (e: any) {
    if (id !== convId.value) return
    // An unreadable ticket is a fact about the READ, never "you have no ticket".
    supportTicket.value = null
    supportErr.value = e?.detail || t('ourstate.support.stateFailed',
      'Could not read this ticket’s status just now.')
  }
}

/** A reply from the thread writes the TICKET; the mirror follows. Posting the
 *  chat message directly would be a second writer and the server refuses it. */
async function sendSupportReply(text: string) {
  sending.value = true
  try {
    const r = await chatApi.supportReply(token.value, convId.value, text)
    if (r?.status && supportTicket.value) supportTicket.value.status = r.status
    input.value = ''
    await load()
  } catch (e: any) { hint.value = e?.detail || String(e) } finally { sending.value = false }
}

/* ── V0654 (aq): wake modes (what of the room wakes a member). The room's owner, signed in, sets a session's here and in
   the side panel; the registry posts one line in the room, to that member alone, and refuses anyone else. ── */
const wakeBusy = ref<string | null>(null)
const membersCanSetWake = ref(false)
function wakeWord(m: string): string {
  return m === 'on-call' ? t('ourstate.wake.onCall', 'On call') : m === 'off' ? t('ourstate.wake.off', 'Off')
    : t('ourstate.wake.listen', 'Listen')
}
async function setWake(key: string, mode: WakeMode): Promise<boolean> {
  if (!key || wakeBusy.value) return false
  wakeBusy.value = key
  try {
    const r = await chatApi.setWakeMode(token.value, convId.value, mode, key)
    if (room.value) room.value = { ...room.value, wake_modes: { ...(room.value.wake_modes || {}), [key]: r?.wake_mode || mode } }
    if (r?.system_message) ingest(r.system_message)
    return true
  } catch (e: any) { hint.value = e?.detail || String(e); return false } finally { wakeBusy.value = null }
}
async function setMemberWake(mb: any, mode: WakeMode) {
  if (await setWake(String(mb.key || ''), mode)) members.value = members.value.map((x: any) => (x.key === mb.key ? { ...x, wake_mode: mode } : x))
}

/* members sheet */
const membersOpen = ref(false)
const members = ref<any[]>([])
async function openMembers() {
  membersOpen.value = true
  try {
    const r = await chatApi.roomMembers(token.value, convId.value)
    members.value = r.members || []
    membersCanSetWake.value = !!r.can_set_wake      // V0654 (aq)
  } catch (e: any) { hint.value = e?.detail || String(e); membersOpen.value = false }
}
function memberOffers(mb: any): RoomActionOffer[] {
  if (!roomCtx.value) return []
  const mv: RoomMemberView = {
    ptype: mb.ptype, id: String(mb.developer_id ?? mb.agent_did ?? ''),
    name: mb.name, orgRole: mb.org_role ?? null,
    canPost: mb.can_post !== false, isMe: !!mb.is_me,
  }
  return memberOps(roomCtx.value, mv)
}
function onMemberOp(op: RoomActionOffer, mb: any) {
  if (op.door === 'org-rail') {
    // The one DOOR out of chat: org removal happens on the org page, its own
    // confirm, its own audit — never through a chat schema.
    membersOpen.value = false
    router.push('/organization').catch(() => {})
    return
  }
  membersOpen.value = false
  roomConfirm.value = {
    action: op.key as any, destructive: op.destructive,
    target: { ptype: mb.ptype, developer_id: mb.developer_id ?? undefined, agent_did: mb.agent_did ?? undefined },
    targetName: mb.name || mb.agent_did || `dev ${mb.developer_id}`,
    value: op.value || '',
  }
}

/* room-op confirm (staged; destructive = hold) */
const roomConfirm = ref<{ action: 'kick' | 'mute' | 'unmute' | 'mode' | 'topic' | 'motd' | 'assistant_on' | 'assistant_off';
                          destructive: boolean; target?: any; targetName?: string; value: string } | null>(null)
const roomBusy = ref(false)
const roomErr = ref('')
const roomConfirmTitle = computed(() => {
  const a = roomConfirm.value?.action
  return a === 'kick' ? 'Remove from room' : a === 'mute' ? 'Mute member'
    : a === 'unmute' ? 'Unmute member' : a === 'mode' ? 'Change room mode'
    : a === 'topic' ? 'Set topic'
    : a === 'assistant_on' ? 'Add @assistant to this room'
    : a === 'assistant_off' ? 'Remove @assistant' : 'Edit room genesis'
})
function stageAssistantToggle() {
  // §ROOMBRAIN — presence rides the room-op rail (a visible system row both
  // ways); the confirm sheet states the read scope BEFORE the decision.
  if (!room.value) return
  roomErr.value = ''
  roomConfirm.value = {
    action: room.value.assistant_present ? 'assistant_off' : 'assistant_on',
    destructive: false, value: '',
  }
}
function stageRoomSettings() {
  // Operator settings v1 = the mode flip (destructive, held) — topic and
  // genesis ride /topic and /motd, which prefill this same confirm.
  if (!roomCtx.value) return
  const flip = roomOps(roomCtx.value).find(o => o.key === 'mode')
  if (!flip) return
  roomErr.value = ''
  roomConfirm.value = { action: 'mode', destructive: true, value: flip.value || 'announce' }
}
async function executeRoomOp() {
  const c = roomConfirm.value
  if (!c || roomBusy.value) return
  roomBusy.value = true; roomErr.value = ''
  try {
    const r = await chatApi.roomAction(token.value, convId.value, {
      action: c.action,
      ...(c.target ? { target: c.target } : {}),
      ...(c.value !== '' || c.action === 'topic' ? { value: c.value } : {}),
    })
    if (r?.system_message) ingest(r.system_message)
    if (room.value) {
      room.value = { ...room.value, mode: r.mode ?? room.value.mode,
                     topic: r.topic ?? room.value.topic, genesis: r.genesis ?? room.value.genesis,
                     ...(c.action === 'assistant_on' || c.action === 'assistant_off'
                       ? { assistant_present: c.action === 'assistant_on' } : {}) }
    }
    roomConfirm.value = null
    input.value = ''
  } catch (e: any) {
    roomErr.value = e?.detail || String(e)   // the 403 names the missing rank
  } finally { roomBusy.value = false }
}
const roomHoldPct = ref(0)
let roomHoldTimer: any = null
function roomHoldStart() {
  const t0 = Date.now()
  roomHoldTimer = setInterval(() => {
    roomHoldPct.value = Math.min(100, ((Date.now() - t0) / 900) * 100)
    if (roomHoldPct.value >= 100) { roomHoldCancel(); void executeRoomOp() }
  }, 50)
}
function roomHoldCancel() { if (roomHoldTimer) { clearInterval(roomHoldTimer); roomHoldTimer = null }; roomHoldPct.value = 0 }

/* ── §OURSTATE-2 mixed-speaker dm ─────────────────────────────────────────
   CORE spoke as YOU in dm threads because the chip must never offer what the
   auth model would refuse. It no longer would: the household rule lets your
   own LOCAL agent post in a thread you are active in, so the chip can offer
   exactly the principals you hold credentials for — and nothing else. */
const speakerPickerOpen = ref(false)
/* §OURSTATE-6 — ONE SELECTION, NOT TWO.
   `speakerDid` used to be its own ref, so the composer held a second identity
   that could disagree with the header's "Acting as" — and did, on his screen,
   with 640 credentials stored. It is now DERIVED from the acting agent, which
   is the field `client.ts` already routes every agent-tier request on
   (§FOREIGNACT: a label attached to an action must come from the field the
   action routes on). The only local state left is whether you have chosen to
   speak as YOURSELF in this thread, which is a real and different thing.
   V0652 (aj): and YOU is the default. The console picks an acting agent by itself at sign-in (stores/auth.ts), so a
   room got messages from an agent nobody chose for it (the maintainer, the room seq 313: "It got accidentally picked
   in the mobile app"). An agent speaks in a thread only when it was chosen there (remembered per thread), and only
   while it is the acting agent, whose token the message is sent with; an agent's service thread keeps the acting
   agent, the rail's payer. services/chat/speakAs.ts holds the rule. */
const threadSpeaker = ref<string | null>(rememberedSpeaker(String(route.params.id || '')))
watch(() => String(route.params.id || ''), (id) => { threadSpeaker.value = rememberedSpeaker(id) })
const speakerDid = computed<string | null>(() => resolveSpeaker({
  isAgentThread: isAgentThread.value,
  activeDid: ((auth as any).activeAgent?.did as string | undefined) || null,
  remembered: threadSpeaker.value,
}))
const speakAsHuman = computed(() => !speakerDid.value)
function chooseSpeaker(did: string | null) {
  threadSpeaker.value = did
  rememberSpeaker(convId.value, did)
}
const localCredAgents = computed(() =>
  credAgents.value.filter(a => !a.registry_url || a.registry_url.startsWith(location.origin)))

function onSpeakerTap() {
  // An agent_service thread's payer is fixed by the rail (the caller IS the
  // payer) — there the chip stays the ONE identity door, as in CORE.
  if (isAgentThread.value) { router.replace({ query: { ...route.query, sheet: 'agent' } }); return }
  speakerPickerOpen.value = true
}

/** The human row. Speaking as yourself is a per-thread choice and touches no
 *  global state — your money keeps routing wherever "Acting as" says. */
function pickHumanSpeaker() {
  chooseSpeaker(null)
  speakerPickerOpen.value = false
}

/** An agent row. The shared list has already authenticated and set the acting
 *  agent; this only has to stop speaking as the human and close. */
function onSpeakerSwitched(did: string) {
  chooseSpeaker(did || null)
  speakerPickerOpen.value = false
}

async function pickSpeaker(did: string | null) {
  if (did === null) { chooseSpeaker(null); speakerPickerOpen.value = false; return }
  const ok = await ensureAgentFor(did)
  if (!ok) { hint.value = t('ourstate.thread.agentAuthFailed', 'Could not authenticate as your agent.'); return }
  chooseSpeaker(did)
  speakerPickerOpen.value = false
}

/** The token the NEXT message is authored with. Agent-authored messages carry
 *  the agent's own identity forever — that is the point of the chip. */
const speakingToken = computed(() =>
  speakerDid.value ? ((auth as any).agentToken || token.value) : token.value)

/* ── V0654 (ap), order gwo_03a846cb91b37628c3c6710a: the assistant in OurChat ──
   His words (the sessions' room seq 1091): pickable per identity in the "send as" choice, the chip amber while it is on,
   his request shown to himself and the answer below it, on the phone and the desktop. Only where his personal assistant
   is enabled for him (GET /assistant/status: the bridge, admin-only), never in an agent's service thread (the rail fixes
   who speaks there) or a support thread (the desk writes it). The registry posts the answer as the identity this thread
   sends with (POST /chat/conversations/{id}/assist); the request is never posted, and stays on this device. */
const assistAvailable = ref(false)
async function loadAssistAvailable() {
  try { assistAvailable.value = !!(await apiClient.get('/assistant/status'))?.data?.bridge?.enabled }
  catch { assistAvailable.value = false }
}
const assistOffered = computed(() => assistAvailable.value && !isAgentThread.value && !isSupportThread.value)
const assistWho = computed(() => speakerDid.value || YOU)
/** the identity in the assistant's sentences: the agent's name, or "you" */
const assistWhoName = computed(() => (speakerDid.value ? speakerLabel.value : t('ourstate.assist.you', 'you')))
const assistOnIds = ref<string[]>(assistantIds(convId.value))
watch(convId, (id) => { assistOnIds.value = assistantIds(id) })
const assistOn = computed(() => assistOffered.value && assistOnIds.value.includes(assistWho.value))
function toggleAssist() {
  assistOnIds.value = rememberAssistant(convId.value, assistWho.value, !assistOn.value)
}
const assistReloaded = () => t('ourstate.assist.reloaded',
  'This page reloaded while the assistant was writing. Ask again: an answer already posted comes back, and nothing is asked twice.')
const asks = ref<AssistAsk[]>(readAsks(convId.value, assistReloaded()))
watch(convId, (id) => { asks.value = readAsks(id, assistReloaded()) })
const roomAsks = computed(() => asks.value.filter(a => a.conversationId === convId.value))
const shownSeqs = computed(() => new Set(shownMessages.value.map((m: any) => Number(m.seq))))
function asksAfter(seq: number): AssistAsk[] { return roomAsks.value.filter(a => a.afterSeq === Number(seq)) }
const asksUnanchored = computed(() => roomAsks.value.filter(a => !shownSeqs.value.has(a.afterSeq)))
function patchAsk(a: AssistAsk, p: Partial<AssistAsk>) {
  const inView = asks.value.some(x => x.ref === a.ref)
  const list = inView ? asks.value : readAsks(a.conversationId, assistReloaded())   // the room was left meanwhile
  const next = list.map(x => (x.ref === a.ref ? { ...x, ...p } : x))
  if (inView) asks.value = next
  writeAsks(a.conversationId, next)
}
async function askAssistant(prompt: string, again?: AssistAsk) {
  const conv = convId.value
  const reply = again ? null : replyTo.value
  const ask: AssistAsk = again ? { ...again, state: 'waiting', error: undefined } : {
    ref: uuid(), conversationId: conv, prompt, who: speakerDid.value ? speakerLabel.value : '', whoKey: assistWho.value, state: 'waiting',
    afterSeq: Number(messages.value[messages.value.length - 1]?.seq || 0), replyTo: reply?.id }
  if (again) patchAsk(again, { state: 'waiting', error: undefined })
  else {
    asks.value = [...asks.value, ask]
    writeAsks(conv, asks.value)
    input.value = ''
    replyTo.value = null
    void nextTick().then(scrollBottom)
  }
  sending.value = true
  try {
    const r = await chatApi.assist(speakingToken.value, conv,
      { prompt: ask.prompt, client_ref: ask.ref, ...(ask.replyTo ? { reply_to: ask.replyTo } : {}) })
    if (conv === convId.value) {
      if (r?.my_state) myState.value = r.my_state
      if (r?.message) ingest(r.message)
    }
    patchAsk(ask, { state: 'answered', answerSeq: Number(r?.message?.seq || 0) || undefined })
  } catch (e: any) {
    patchAsk(ask, { state: 'failed', error: e?.status ? (e?.detail || String(e)) : t('ourstate.assist.offline',
      'No answer reached this device (the connection dropped). Ask again: an answer already posted comes back, and nothing is asked twice.') })
  } finally { sending.value = false }
}
function dropAsk(a: AssistAsk) {
  asks.value = asks.value.filter(x => x.ref !== a.ref)
  writeAsks(a.conversationId, asks.value)
}
function retryAsk(a: AssistAsk) {
  if (sending.value) return
  // asking again goes out as the identity it was asked for, or not at all (another identity would answer for it)
  if (a.whoKey && a.whoKey !== assistWho.value) {
    hint.value = tp('ourstate.assist.retryWho', 'Speak as {who} again to ask again.', { who: a.who || t('ourstate.assist.yourself', 'yourself') })
    return
  }
  void askAssistant(a.prompt, a)
}
function editAsk(a: AssistAsk) {
  input.value = a.prompt
  dropAsk(a)
  void nextTick().then(() => inputEl.value?.focus())
}
function dismissAsk(a: AssistAsk) { dropAsk(a) }

/* ── §OURSTATE-2 batch 2b: WORK pointers, /ledger, away kill switch ── */
const pageBound = ref(40)

/* /ledger — local, bounded, currency-honest */
const ledgerOpen = ref(false)
const ledger = ref<LedgerView | null>(null)

/* WORK: share a pointer (/work) and open one (card door) */
const workPickerOpen = ref(false)
const workBusy = ref(false)
const workItems = ref<Array<{ kind: 'contract.offer' | 'guild.order'; ref: string; title: string
                              amount: string | null; currency: string | null; status: string }>>([])

async function openWorkPicker() {
  workPickerOpen.value = true
  workBusy.value = true
  workItems.value = []
  try {
    const okAgent = await ensureActingAgent()
    const jwt = okAgent ? (auth as any).agentToken : null
    const items: typeof workItems.value = []
    if (jwt) {
      // Both rails are AGENT-scoped by construction — you can only ever share
      // engagements you are actually a party to.
      const [g, c] = await Promise.all([
        fetch('/api/v1/guild/mine', { headers: { Authorization: `Bearer ${jwt}` } })
          .then(r => r.ok ? r.json() : null).catch(() => null),
        fetch('/api/v1/contracts/v2/mine', { headers: { Authorization: `Bearer ${jwt}` } })
          .then(r => r.ok ? r.json() : null).catch(() => null),
      ])
      for (const o of (g?.orders || g?.items || [])) {
        items.push({ kind: 'guild.order', ref: String(o.id ?? o.order_id ?? ''),
                     title: String(o.title || o.summary || 'guild order'),
                     amount: o.bounty != null ? String(o.bounty) : null,
                     currency: o.currency || null, status: String(o.status || '') })
      }
      for (const k of (c?.items || c?.contracts || [])) {
        items.push({ kind: 'contract.offer', ref: String(k.ref ?? k.contract_ref ?? k.id ?? ''),
                     title: String(k.title || k.description || 'contract'),
                     amount: k.total_amount != null ? String(k.total_amount) : null,
                     currency: k.currency || null, status: String(k.status || '') })
      }
    }
    workItems.value = items.filter(i => i.ref)
  } finally { workBusy.value = false }
}

async function shareWork(item: typeof workItems.value[number]) {
  workPickerOpen.value = false
  const card = buildWorkCard(item.kind, item.ref, item.title, {
    amount: item.amount, currency: item.currency, status: item.status,
  })
  sending.value = true
  try {
    const r = await chatApi.postMessage(token.value, convId.value, { kind: 'card', card, client_ref: uuid() })
    ingest(r.message)
  } catch (e: any) { hint.value = e?.detail || String(e) } finally { sending.value = false }
}

function openWorkDoor(p: { kind: 'contract.offer' | 'guild.order'; ref: string }) {
  // A DOOR: the work rail does the awarding, delivering and settling. Guild
  // orders land on their own sheet in Earn (?order=), contracts on the WORK
  // view — both are surfaces that already exist and already gate themselves.
  if (p.kind === 'guild.order') router.push(`/pocket/payments?order=${encodeURIComponent(p.ref)}`).catch(() => {})
  else router.push(`/contracts?ref=${encodeURIComponent(p.ref)}`).catch(() => {})
}

/** §OURCHAT-ORG — the venue door. `PocketTrade` has accepted `?sym=` since it
 *  shipped and consumes-then-scrubs the query, so this is an address for a
 *  ticket that already exists. Deliberately NO side and NO quantity: the card
 *  names what is being talked about, and the person composes the order. */
function openTradeDoor(p: { symbol: string }) {
  const sym = String(p.symbol || '').trim().toUpperCase()
  if (!sym) {
    hint.value = t('ourstate.card.tradeNoSymbol', 'That card names no symbol to trade.')
    return
  }
  router.push(`/pocket/trade?sym=${encodeURIComponent(sym)}`).catch(() => {})
}

/* Away mode: the per-thread kill switch (the owner's stand-in stops here) */
const awayCfg = ref<any | null>(null)
const awaySilencedHere = computed(() =>
  !!awayCfg.value?.enabled && (awayCfg.value?.threads_off || []).includes(convId.value))
async function loadAway() {
  try {
    const r = await apiClient.get('/developers/me/prefs/pocket.away')
    awayCfg.value = r.data?.value || null
  } catch { awayCfg.value = null }
}
async function toggleAwayHere() {
  const cfg = { ...(awayCfg.value || {}) }
  const off = new Set<string>(cfg.threads_off || [])
  if (off.has(convId.value)) off.delete(convId.value); else off.add(convId.value)
  cfg.threads_off = [...off]
  try {
    await apiClient.put('/developers/me/prefs/pocket.away', { value: cfg })
    awayCfg.value = cfg
    menuOpen.value = false
  } catch (e: any) { hint.value = e?.detail || String(e) }
}

/** /kick·/mute·/unmute typed a NAME — resolve it against the member sheet;
    ambiguity opens the sheet instead of guessing (a moderation act never
    lands on a fuzzy match). */
async function stageRoomTargetOp(op: 'kick' | 'mute' | 'unmute', targetText: string) {
  try {
    const r = await chatApi.roomMembers(token.value, convId.value)
    members.value = r.members || []
  } catch (e: any) { hint.value = e?.detail || String(e); return }
  const q = targetText.trim().toLowerCase()
  const hits = members.value.filter(mb => !mb.is_me &&
    ((mb.name || '').toLowerCase().includes(q) || String(mb.agent_did || '').toLowerCase() === q))
  if (hits.length === 1) {
    const mb = hits[0]
    const offer = memberOffers(mb).find(o => o.key === op)
    if (!offer) { hint.value = t('ourstate.rooms.cannotAct', 'You cannot act on that member (equal or higher rank).'); return }
    onMemberOp(offer, mb)
    input.value = ''
  } else {
    hint.value = hits.length === 0
      ? tp('ourstate.rooms.noMatch', 'No member matches “{q}” — pick from the sheet.', { q: targetText })
      : tp('ourstate.rooms.ambiguous', '{n} members match — pick from the sheet.', { n: String(hits.length) })
    membersOpen.value = true
  }
}

/* service call */
/* §CHATCOHERE D4 — the confirm sheet stated a PRICE and offered a Call button,
   and never said whether the purse could cover it. Measured on a cold start: the
   only way to learn you held nothing was to press Call and be refused. `held` is
   what the acting agent's own ledger answers; `null` means "we could not read
   it", which renders as SILENCE rather than as a guess. */
const callConfirm = ref<{ ask: string; quote: any | null; held: string | null } | null>(null)
const callSheetEl = ref<HTMLElement | null>(null)
useFocusTrap(callSheetEl, { activeWhen: computed(() => !!callConfirm.value) })

async function stageServiceCall(ask: string) {
  if (!counterpartyDid.value) { hint.value = t('ourstate.thread.noAgentTarget', 'This thread has no service agent to call.'); return }
  const okAgent = await ensureActingAgent()
  if (!okAgent) return
  let quote: any = null
  try {
    const r = await fetch(`/api/v1/a2a-payment/quote?target_agent_did=${encodeURIComponent(counterpartyDid.value)}`,
      { headers: { Authorization: `Bearer ${(auth as any).agentToken}` } })
    if (r.ok) quote = await r.json()
  } catch { /* quote absent → confirm still states the honest unknown */ }
  callConfirm.value = { ask, quote, held: await readHeld() }
}

/** What the acting agent holds, as a plain string — or null when the ledger did
 *  not answer. Same rail and same DID predicate as `showBalance()`; a failed read
 *  is null, never 0, because "we could not check" and "you have nothing" are
 *  different facts and only one of them should stop a person. */
async function readHeld(): Promise<string | null> {
  const did = walletDid.value
  if (!did) return null
  try {
    const raw: any = await developerApi.getAgentBalancesBatch([did])
    const b = (raw?.balances || raw || {})[did] || {}
    const liquid = b.liquid_balance ?? b.balance
    if (liquid === undefined || liquid === null) return null
    /* §CHATCOHERE — the TEG answers in scientific notation (`0E-18`), which is a
       number to a parser and gibberish to a person. Same helper the cards use. */
    return displayAmount(String(liquid)) || String(liquid)
  } catch { return null }
}

/** True only when BOTH numbers are readable and the purse is genuinely short.
 *  Unknown ⇒ false: the sheet never accuses a purse it could not read. */
const callShort = computed<boolean>(() => {
  const c = callConfirm.value
  if (!c || !c.held || !c.quote?.payment_required) return false
  const need = Number(c.quote.recommended_amount ?? c.quote.your_amount)
  const have = Number(c.held)
  return Number.isFinite(need) && Number.isFinite(have) && have < need
})

async function ensureActingAgent(): Promise<boolean> {
  const local = credAgents.value.filter(a => !a.registry_url || a.registry_url.startsWith(location.origin))
  if (!local.length) { hint.value = noAgentReason.value || t('ourstate.thread.needAgent', 'Add an agent with credentials to call services (Agents → import or adopt).'); return false }
  const preferred = (auth as any).activeAgent?.did && local.some(a => a.did === (auth as any).activeAgent.did)
    ? (auth as any).activeAgent.did : local[0].did
  const ok = await ensureAgentFor(preferred)
  if (!ok) hint.value = t('ourstate.thread.agentAuthFailed', 'Could not authenticate as your agent.')
  return ok
}

async function runServiceCall() {
  const staged = callConfirm.value
  if (!staged) return
  // Priced call = a money moment: the pocket lock gates it (biometric where enrolled).
  if (staged.quote?.payment_required) {
    // The proven Earn gate: enrolled lock => biometric verify before money.
    if (lock.enabled.value && !(await lock.verify().catch(() => false))) {
      hint.value = t('ourstate.thread.lockRefused', 'Verification failed or cancelled.'); return
    }
  }
  serviceBusy.value = true
  callConfirm.value = null
  try {
    const r = await chatApi.serviceCall((auth as any).agentToken, convId.value,
      { client_ref: uuid(), text: staged.ask })
    input.value = ''
    if (r?.call_message) ingest(r.call_message)
    if (r?.result_message) ingest(r.result_message)
  } catch (e: any) {
    hint.value = e?.detail || String(e)
  } finally { serviceBusy.value = false; void load() }
}

/* the send button */
async function send() {
  hint.value = ''; hintSendAsText.value = false
  const raw = input.value.trim()
  if (!raw) return
  const intent = parseComposer(raw, composerCtx.value)
  switch (intent.kind) {
    case 'text':
      if (isSupportThread.value) return sendSupportReply(raw)
      if (isAgentThread.value) return stageServiceCall(raw)
      if (assistOn.value) return askAssistant(raw)
      return postText(raw)
    case 'me':
      return postText(`/me ${intent.action}`)
    case 'pay': {
      if (intent.refusal === 'amount-missing') { hint.value = t('ourstate.thread.amountMissingPay', '/pay needs an amount — /pay 12,5'); return }
      if (intent.refusal === 'currency-unresolved') { hint.value = t('ourstate.thread.ccyUnresolvedPay', 'Currency unknown — the acting registry has not answered yet. Name one: /pay 12,5 BVT'); return }
      sendPrefill.value = { to: counterpartyDid.value || undefined,
        amount: intent.amount != null ? String(intent.amount) : undefined, memo: intent.memo || undefined }
      sendEver.value = true; sendOpen.value = true
      input.value = ''
      return
    }
    case 'request': {
      if (intent.refusal === 'amount-missing') { hint.value = t('ourstate.thread.amountMissingReq', '/request needs an amount — /request 12,5'); return }
      if (intent.refusal === 'currency-unresolved') { hint.value = t('ourstate.thread.ccyUnresolvedReq', 'Currency unknown — the acting registry has not answered yet. Name one: /request 12,5 BVT'); return }
      const card = buildPayRequest(String(intent.amount), intent.currency as string, intent.memo)
      sending.value = true
      try {
        const r = await chatApi.postMessage(token.value, convId.value, { kind: 'card', card, client_ref: uuid() })
        ingest(r.message); input.value = ''
      } catch (e: any) { hint.value = e?.detail || String(e) } finally { sending.value = false }
      return
    }
    case 'quote': {
      if (!isAgentThread.value) { hint.value = t('ourstate.thread.quoteOnlyAgents', '/quote works in agent threads.'); return }
      return stageServiceCall(t('ourstate.thread.quoteProbe', '(quote check)'))
    }
    case 'call':
      if (!isAgentThread.value) { hint.value = t('ourstate.thread.callOnlyAgents', '/call works in agent threads.'); return }
      if (!intent.ask) { hint.value = t('ourstate.thread.callNeedsAsk', '/call needs an ask — /call weather in Berlin'); return }
      return stageServiceCall(intent.ask)
    case 'audit':
      auditDid.value = intent.target || counterpartyDid.value
      if (!auditDid.value) { hint.value = t('ourstate.thread.auditNeedsAgent', '/audit needs an agent counterparty or target DID.'); return }
      auditOpen.value = true; input.value = ''
      void loadAuditAuthority()
      return
    case 'timer':
      input.value = ''
      timerOpen.value = true
      return
    // §OURSTATE-6 — three doors, no actions. Each lands on a surface that
    // already exists; none of them sends, pays, files or rates anything.
    case 'propose':
      // §DEALTHREADS — FILLS the composer sheet; the human posts from there.
      input.value = ''
      openPropose({ title: intent.title, total: null, note: null })
      return
    case 'find':
      input.value = ''
      router.push({ path: base.value,
                    query: { find: '1', ...(intent.query ? { fq: intent.query } : {}) } }).catch(() => {})
      return
    case 'here':
      input.value = ''
      return openHere()
    case 'dispute':
      input.value = ''
      // The WORK modal's disputes lane (§POCKETBRIDGE5) is the ONE place a
      // dispute is filed. Opening it here is a shortcut to that surface, not
      // a second way to file — filing still happens there, with its own words.
      router.push({ path: base.value, query: { work: 'disputes' } }).catch(() => {})
      return
    case 'ledger':
      // Local-only, from what THIS page can see — and it says so.
      ledger.value = buildLedger(messages.value, isMine, pageBound.value)
      ledgerOpen.value = true
      input.value = ''
      return
    case 'work':
      input.value = ''
      return openWorkPicker()
    case 'ping': {
      sending.value = true
      try { const r = await chatApi.ping(token.value, convId.value, uuid()); ingest(r.message); input.value = '' }
      catch (e: any) { hint.value = e?.detail || String(e) } finally { sending.value = false }
      return
    }
    case 'card':
      return resolveAndShareCard(intent.query)
    case 'stock':
      return resolveAndShareListing(intent.symbol)
    case 'stocks':
      return showStockList((intent as any).query)
    case 'balance':
      return showBalance()
    case 'ignore':
      blockConfirm.value = true; input.value = ''
      return
    case 'help':
      input.value = ''
      helpExpanded.value = new Set()   // §CHATCOHERE A4 — every open starts folded
      helpOpen.value = true
      return
    case 'room-op': {
      if (intent.refusal === 'not-a-room') { hint.value = t('ourstate.rooms.notARoom', 'Room commands work inside an org room.'); return }
      if (intent.refusal === 'not-operator') { hint.value = t('ourstate.rooms.notOperator', 'Room operations need an org owner or admin.'); return }
      if (intent.refusal === 'target-missing') { hint.value = tp('ourstate.rooms.targetMissing', '/{op} needs a member — /{op} Dana', { op: intent.op }); return }
      if (intent.op === 'kick' || intent.op === 'mute' || intent.op === 'unmute') {
        return stageRoomTargetOp(intent.op, intent.target)
      }
      // topic / motd: prefill the confirm (motd starts from the current
      // genesis when typed bare — an edit, not a blind overwrite).
      roomErr.value = ''
      roomConfirm.value = {
        action: intent.op, destructive: false,
        value: intent.value || (intent.op === 'motd' ? (room.value?.genesis?.stated || '') : ''),
      }
      return
    }
    case 'room-settings':
      if (intent.refusal === 'not-a-room') { hint.value = t('ourstate.rooms.notARoom', 'Room commands work inside an org room.'); return }
      if (intent.refusal === 'not-operator') { hint.value = t('ourstate.rooms.notOperator', 'Room operations need an org owner or admin.'); return }
      input.value = ''
      stageRoomSettings()
      return
    case 'room-invite':
      if (intent.refusal === 'not-a-room') { hint.value = t('ourstate.rooms.notARoom', 'Room commands work inside an org room.'); return }
      // The org rail's own invite — a door, never a chat write.
      input.value = ''
      router.push('/organization').catch(() => {})
      return
    case 'unknown-slash':
      hint.value = tp('ourstate.thread.unknownSlash', 'Unknown command {cmd} — /help lists them.', { cmd: intent.cmd })
      hintSendAsText.value = true
      return
  }
}

/* ── thread actions ── */
async function acceptThread() { try { const r = await chatApi.accept(token.value, convId.value); myState.value = r.my_state } catch (e: any) { hint.value = e?.detail || String(e) } }
async function declineThread() { try { await chatApi.decline(token.value, convId.value); router.push(base.value) } catch (e: any) { hint.value = e?.detail || String(e) } }

const blockConfirm = ref(false)
async function doBlock() {
  const cp = counterparty.value
  if (!cp) return
  // §TWOAGENT G1 household/V0436: one mapping for all three kinds; a counterparty on a peer registry is blocked by its
  // address (it used to be sent as a developer with no id, which the server can only refuse)
  const target = blockTargetFor(cp)
  if (!target) {
    hint.value = t('ourstate.thread.blockUnavailable', 'This counterparty cannot be blocked from this screen.')
    return
  }
  try {
    await chatApi.block(token.value, target)
    router.push(base.value)
  } catch (e: any) { hint.value = e?.detail || String(e) }
}

/* ── V0652 (ak) (order gwo_8c69cc0fd1f3033a35f47969): the thread's settings ───────────────────────────────────
   One menu (ChatSettingsMenu) for the console's #/ourchat, Pocket wide and the phone; each row hands its act back
   here. The design: sessionlogs2026/DESIGN_2026-11-01_OURCHAT_SETTINGS.md; session-lead's review: seq 397. */
const menuBtn = ref<HTMLElement | null>(null)
const wideMq = typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia('(min-width: 900px)') : null
const wideMenu = ref(!!wideMq?.matches)         // OurChatShell's own breakpoint: two panes, a menu; one pane, a sheet
const onWide = () => { wideMenu.value = !!wideMq?.matches }
const inPocket = computed(() => String(route.path || '').startsWith('/pocket'))
const burnOpen = ref(false)
const notifyOpen = ref(false)
const notifyBusy = ref(false)
const notifyErr = ref('')
const mutedUntil = ref<string | null>(null)
const roomSettingsOpen = ref(false)
const roomSettingsEl = ref<any>(null)
const leaveConfirm = ref(false)
const leaveBusy = ref(false)
const youOpen = ref(false)
const pushState = ref<'on' | 'off' | 'unknown' | 'unsupported'>('unknown')
const nowTick = ref(Date.now())
const mutedNow = computed(() => muteInEffect(muted.value, mutedUntil.value, nowTick.value))
const settingsKind = computed<'room' | 'dm' | 'support'>(() => (room.value ? 'room' : isSupportThread.value ? 'support' : 'dm'))
const counterpartyName = computed(() => String(counterparty.value?.name || ''))
const hostReg = computed(() => String(hosting.value?.registry || ''))
const settingsTitle = computed(() => (settingsKind.value === 'room' ? String(room.value?.title || t('ourstate.rooms.room', 'Org room'))
  : settingsKind.value === 'support' ? t('ourstate.support.desk', 'Support')
  : (counterpartyName.value || t('ourstate.settings.thisChat', 'This chat'))))
const settingsSubline = computed(() => {
  const parts: string[] = []
  if (settingsKind.value === 'room') {
    parts.push(t('ourstate.settings.kindRoom', 'Org room'))
    // one measure, labelled (review item 11): who has opened the room
    if (room.value?.member_count != null) parts.push(tp('ourstate.settings.opened', '{n} opened it', { n: String(room.value.member_count) }))
  } else if (settingsKind.value === 'support') {
    parts.push(supportTicket.value ? tp('ourstate.settings.ticket', 'Ticket #{id}', { id: String(supportTicket.value.ticket_id) })
      : t('ourstate.support.desk', 'Support'))
  } else {
    parts.push(t('ourstate.settings.kindDm', 'Direct'))
  }
  if (hostReg.value) parts.push(tp('ourstate.settings.hostedBy', 'hosted by {reg}', { reg: hostReg.value }))
  return parts.join(' · ')
})
const settingsRoom = computed(() => (room.value ? { opened: room.value.member_count ?? null, isOperator: !!room.value.my_is_operator,
  mode: String(room.value.mode || 'open'), assistantPresent: !!room.value.assistant_present } : null))
const timerWord = computed(() => {
  const h = retentionHours.value
  if (!h) return t('ourstate.settings.off', 'Off')
  if (h === 1) return t('ourstate.settings.oneHour', '1 hour')
  if (h < 24) return tp('ourstate.settings.hours', '{n} hours', { n: String(h) })
  if (h === 24) return t('ourstate.settings.oneDay', '1 day')
  return tp('ourstate.settings.days', '{n} days', { n: String(Math.round(h / 24)) })
})
/* who may set the timer: either side of a direct chat; in an organization's room an owner or an admin (the server's
   rule since V0652 (ak)); a support thread has none */
const timerEditable = computed(() => settingsKind.value === 'dm' || (settingsKind.value === 'room' && !!room.value?.my_is_operator))
const notifyWord = computed(() => {
  if (mutedNow.value) {
    const what = settingsKind.value === 'support' ? t('ourstate.notify.muted', 'Muted') : t('ourstate.notify.asksOnly', 'Only asks for me')
    return mutedUntil.value ? tp('ourstate.settings.notifyUntil', '{what} · until {when}',
      { what, when: timeLabel(mutedUntil.value, nowTick.value, appLocale()) }) : what
  }
  return settingsKind.value === 'room' ? t('ourstate.notify.needs', 'Mentions and asks')
    : settingsKind.value === 'dm' ? t('ourstate.notify.every', 'Every message') : t('ourstate.notify.everyReply', 'Every reply')
})
const readersLine = computed(() => {
  const reg = hostReg.value || t('pocket.send.thisRegistry', 'this registry')
  const copies = (hosting.value?.copies || []).filter(Boolean)
  const who = settingsKind.value === 'room' ? tp('ourstate.settings.readersRoom', "The members, and {reg}'s operator", { reg })
    : settingsKind.value === 'support' ? tp('ourstate.settings.readersSupport', "You, the support desk, and {reg}'s operator", { reg })
    : tp('ourstate.settings.readersDm', "You two, and {reg}'s operator", { reg })
  return copies.length ? tp('ourstate.settings.readersCopies', '{who}; copies at {copies}', { who, copies: copies.join(', ') }) : who
})
const settingsAway = computed(() => (settingsKind.value === 'dm'
  ? { enabled: !!awayCfg.value?.enabled, silencedHere: !!awaySilencedHere.value } : null))
/* a person or an agent can be blocked; a room has nobody to block, and a support thread is a rail (inventory item 8) */
const canBlock = computed(() => settingsKind.value === 'dm' && !!counterparty.value)
const settingsTicket = computed(() => (supportTicket.value
  ? { id: supportTicket.value.ticket_id, status: supportStatusWord(supportTicket.value.status) } : null))

function closeMenu() { menuOpen.value = false; void nextTick(() => menuBtn.value?.focus()) }
/* the phone's back gesture closes the settings sheet, not the thread (review item 16): the open sheet is one history
   entry (?settings=1); back removes it and closes the sheet; closing it any other way steps back over it once */
let menuPushed = false
/* the menu and every sheet a row opens are one layer: the entry holds while any of them is open (follow-up, seq 406) */
const settingsLayerOpen = computed(() => menuOpen.value || notifyOpen.value || burnOpen.value || roomSettingsOpen.value
  || youOpen.value || leaveConfirm.value || timerOpen.value || privacyOpen.value || membersOpen.value || blockConfirm.value
  || !!roomConfirm.value)
watch(settingsLayerOpen, (open) => {
  if (open && !wideMenu.value && route.query.settings !== '1') {
    menuPushed = true
    router.push({ query: { ...route.query, settings: '1' } }).catch(() => { menuPushed = false })
  } else if (!open && menuPushed) {
    menuPushed = false
    if (route.query.settings === '1') router.back?.()
  }
})
watch(() => route.query.settings, (now, before) => {
  if (before === '1' && now !== '1' && settingsLayerOpen.value) { menuPushed = false; closeTopSheet() }
})
function onSettingsPick(a: string) {
  menuOpen.value = false
  nowTick.value = Date.now()
  if (a === 'members') void openMembers()
  else if (a === 'room') { roomErr.value = ''; roomSettingsOpen.value = true }
  else if (a === 'assistant') stageAssistantToggle()
  else if (a === 'timer') timerOpen.value = true
  else if (a === 'privacy') void openPrivacy()
  else if (a === 'notify') { notifyErr.value = ''; notifyOpen.value = true }
  else if (a === 'away') void toggleAwayHere()
  else if (a === 'block') blockConfirm.value = true
  else if (a === 'you') { youOpen.value = true; void readPushState() }
  else if (a === 'burn') burnOpen.value = true
  else if (a === 'leave') leaveConfirm.value = true
}

/* burn for you: the confirm said what happens first, and its hold was the confirmation */
async function burnNow() {
  burnOpen.value = false
  try {
    await chatApi.burn(token.value, convId.value)
    // §OURSTATE-5d — destroy the device copy BEFORE saying anything about
    // it, and only claim "encrypted" if there actually was an encrypted
    // one (§11: the word has to be earned).
    const hadCopy = cacheAvailable()
    dropThread(convId.value)
    const deviceNote = burnDeviceNote(hadCopy)
    // The plain-words footnote, once, at the moment of burning (law 5).
    hint.value = t('ourstate.thread.burnFootnote', 'Burned for you. The other side may keep copies; this registry retains the thread until account deletion.')
      + (deviceNote ? ' ' + t('ourstate.thread.burnDevice', 'The copy on this device was encrypted and has been deleted.') : '')
    try { localStorage.removeItem(draftKey.value) } catch { /* ignore */ }
    setTimeout(() => router.push(base.value), 1400)
  } catch (e: any) { hint.value = e?.detail || String(e) }
}

async function saveNotify(v: { muted: boolean; until: string | null; keep: boolean }) {
  if (v.keep) { notifyOpen.value = false; return }
  notifyBusy.value = true; notifyErr.value = ''
  try {
    const r: any = await chatApi.mute(token.value, convId.value, v.muted, v.muted ? v.until : null)
    muted.value = !!r.muted
    mutedUntil.value = r.muted_until ?? null
    notifyOpen.value = false
  } catch (e: any) { notifyErr.value = e?.detail || String(e) } finally { notifyBusy.value = false }
}

async function saveRoomText(v: { topic: string; rules: string; topicChanged: boolean; rulesChanged: boolean }) {
  if (roomBusy.value) return
  roomBusy.value = true; roomErr.value = ''
  try {
    const steps: Array<['topic' | 'motd', string]> = []
    if (v.topicChanged) steps.push(['topic', v.topic])
    if (v.rulesChanged) steps.push(['motd', v.rules])
    for (const [action, value] of steps) {
      const r: any = await chatApi.roomAction(token.value, convId.value, { action, value })
      if (r?.system_message) ingest(r.system_message)
      if (room.value) {
        room.value = { ...room.value, mode: r.mode ?? room.value.mode, topic: r.topic ?? room.value.topic,
                       genesis: r.genesis ?? room.value.genesis }
      }
    }
    roomSettingsOpen.value = false
  } catch (e: any) { roomErr.value = e?.detail || String(e) } finally { roomBusy.value = false }
}
/* who may post: the existing held confirm (it silences people) */
function stageModeChange(mode: 'open' | 'announce') {
  roomSettingsOpen.value = false
  roomErr.value = ''
  roomConfirm.value = { action: 'mode', destructive: true, value: mode }
}

async function doLeave() {
  if (leaveBusy.value) return
  leaveBusy.value = true
  try {
    await chatApi.leave(token.value, convId.value)
    leaveConfirm.value = false
    router.push(base.value)
  } catch (e: any) { hint.value = e?.detail || String(e); leaveConfirm.value = false } finally { leaveBusy.value = false }
}

/* this device's push, read (never assumed): on, off (the opt-in shows), or not possible here */
async function readPushState() {
  try {
    if (!('serviceWorker' in navigator) || !('PushManager' in window) || typeof Notification === 'undefined') {
      pushState.value = 'unsupported'; return
    }
    const reg = await navigator.serviceWorker.getRegistration()
    const sub = reg ? await reg.pushManager.getSubscription() : null
    pushState.value = sub && Notification.permission === 'granted' ? 'on' : 'off'
  } catch { pushState.value = 'unknown' }
}
async function enablePushFromPanel() { await enablePush(); await readPushState() }

/* ── push opt-in (D3): default OFF, one tap, names what it does ── */
const showPushCard = ref(false)
const pushBusy = ref(false)
const pushMsg = ref('')
function dismissPushCard() { showPushCard.value = false; try { localStorage.setItem('os_push_card_dismissed', '1') } catch { /* ignore */ } }
async function checkPushCard() {
  try {
    if (localStorage.getItem('os_push_card_dismissed') === '1') return
    if (!('Notification' in window) || !('serviceWorker' in navigator)) return
    if (Notification.permission === 'denied') return
    const reg = await navigator.serviceWorker.ready
    const sub = await reg.pushManager.getSubscription()
    showPushCard.value = !sub
  } catch { showPushCard.value = false }
}
function urlB64ToUint8Array(b64: string) {
  const pad = '='.repeat((4 - (b64.length % 4)) % 4)
  const raw = atob((b64 + pad).replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from([...raw].map(c => c.charCodeAt(0)))
}
async function enablePush() {
  pushBusy.value = true; pushMsg.value = ''
  try {
    const perm = await Notification.requestPermission()
    if (perm !== 'granted') { pushMsg.value = t('ourstate.thread.pushDenied', 'Permission was not granted.'); return }
    const { application_server_key } = await devicePushApi.webpushKey()
    if (!application_server_key) { pushMsg.value = t('ourstate.thread.pushNoKey', 'This registry has no push key configured.'); return }
    const reg = await navigator.serviceWorker.ready
    const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlB64ToUint8Array(application_server_key) })
    await devicePushApi.webpushSubscribe(sub.toJSON() as any, 'This device')
    // V0652 (z): this tap turns on the pushes for what NEEDS you: a mention, a direct message, a stranger's first
    // message, an approval you decide, a ping. A room's other traffic stays in the app (chat.message is in-app only;
    // the card used to turn pushes on for all of it). The first four push by default too; the rows make the tap win
    // over a channel master switched off earlier.
    await apiClient.put('/notifications/prefs', { rows: pushOptInRows() })
    showPushCard.value = false
    pushMsg.value = t('ourstate.thread.pushOnNeeds', 'On. Mentions, direct messages and approvals to decide reach this device.')
  } catch (e: any) {
    pushMsg.value = e?.message || t('ourstate.thread.pushFailed', 'Could not enable notifications.')
  } finally { pushBusy.value = false }
}

/* Escape closes sheets (window listener — the PocketSend pattern; a @keydown
   on a non-focusable overlay never fires). */
function onKey(e: KeyboardEvent) {
  if (e.key !== 'Escape' || e.defaultPrevented) return   // a press a dialog already used (useEscapeClose) is not ours
  closeTopSheet()
}
/* the topmost open sheet closes (Escape, and the phone's back gesture) */
function closeTopSheet() {
  if (cardHistoryFor.value) cardHistoryFor.value = null
  else if (callConfirm.value) callConfirm.value = null
  else if (burnOpen.value) burnOpen.value = false
  else if (notifyOpen.value) notifyOpen.value = false
  else if (leaveConfirm.value) leaveConfirm.value = false
  else if (youOpen.value) youOpen.value = false
  else if (roomSettingsOpen.value) { if (roomSettingsEl.value?.tryClose) roomSettingsEl.value.tryClose(); else roomSettingsOpen.value = false }
  else if (proposeOpen.value) proposeOpen.value = false
  else if (engageConfirm.value) engageConfirm.value = null
  else if (hereOpen.value) hereOpen.value = false
  else if (timerOpen.value) timerOpen.value = false
  else if (askBackOpen.value) askBackOpen.value = false
  else if (privacyOpen.value) privacyOpen.value = false
  else if (stockListOpen.value) stockListOpen.value = false
  else if (balanceOpen.value) balanceOpen.value = false
  else if (helpOpen.value) helpOpen.value = false
  else if (speakerPickerOpen.value) speakerPickerOpen.value = false
  else if (ledgerOpen.value) ledgerOpen.value = false
  else if (workPickerOpen.value) workPickerOpen.value = false
  else if (roomConfirm.value) { roomHoldCancel(); roomConfirm.value = null }
  else if (membersOpen.value) membersOpen.value = false
  else if (auditOpen.value) auditOpen.value = false
  else if (blockConfirm.value) blockConfirm.value = false
  else if (menuOpen.value) closeMenu()
}

onMounted(() => {
  void loadAssistAvailable()   // V0654 (ap)
  window.addEventListener('keydown', onKey)
  wideMq?.addEventListener?.('change', onWide)
  measurePane()
  if (typeof ResizeObserver !== 'undefined' && rootEl.value) { paneRo = new ResizeObserver(measurePane); paneRo.observe(rootEl.value) }
  else window.addEventListener('resize', measurePane)
  window.addEventListener('online', outboxReplay)
  try { input.value = localStorage.getItem(draftKey.value) || '' } catch { /* ignore */ }
  // §OURSTATE-2 voice door: a spoken draft prefills the composer and is then
  // SCRUBBED from the URL (consume-then-scrub — a draft that survives a reload
  // would resurrect words the human already dismissed).
  const spoken = String(route.query.draft || '')
  if (spoken) {
    input.value = spoken
    router.replace({ query: { ...route.query, draft: undefined } }).catch(() => {})
  }
  // §VOICEHIRE — the offer door: open the S proposal composer PREFILLED, then
  // scrub (consume-then-scrub, the ?draft law — a reload must not resurrect
  // an offer the human already dismissed). Filling is the terminal state.
  if (route.query.propose) {
    proposeForm.value = {
      title: String(route.query.ptitle || ''),
      total: String(route.query.ptotal || ''),
      note: '', supersedes: '',
    }
    proposeOpen.value = true
    router.replace({ query: { ...route.query, propose: undefined, ptitle: undefined, ptotal: undefined, pccy: undefined, x: undefined } }).catch(() => {})
  }
  void load()
  void outboxReplay()
  void checkPushCard()
  void loadAway()
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('online', outboxReplay)
  roomHoldCancel()
  wideMq?.removeEventListener?.('change', onWide)
  paneRo?.disconnect()
  window.removeEventListener('resize', measurePane)
  endAnchor()
})

watch(convId, () => { endAnchor(); messages.value = []; openThreads.value = new Set(); closedThreads.value = new Map(); replyTo.value = null; void load() })
</script>

<style scoped>
.ost { display: flex; flex-direction: column; height: 100%; }
/* V0652 (ad): the column and, when it shows, the side panel beside it; with no panel the column is the whole width */
.ost-body { flex: 1; min-height: 0; display: flex; }
.ost-col { flex: 1 1 auto; min-width: 0; min-height: 0; display: flex; flex-direction: column; }
.ost-head { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-bottom: 1px solid var(--border-color, rgba(128,128,128,.2)); }
.ost-back, .ost-menu-btn { min-width: 44px; min-height: 44px; border: none; background: none; color: inherit; display: grid; place-items: center; cursor: pointer; }
/* V0652 (ak): the settings button names itself (a bare glyph at the far edge was missed), 44 px tall on every surface */
.ost-settings-btn { display: inline-flex; align-items: center; gap: 6px; padding: 0 12px; border: 1px solid var(--nc-border-strong, #343a4d);
  border-radius: 8px; font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .68rem; letter-spacing: .14em; text-transform: uppercase; }
.ost-settings-btn.open { border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), .7); color: var(--nc-primary, #00d2d2);
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), .1); }
.ost-ghost-btn { background: none; }
.ost-settings-word { white-space: nowrap; }
.ost-roster-door { color: var(--nc-primary, #00d2d2); text-decoration: none; white-space: nowrap; }
.ost-who { flex: 1; min-width: 0; }
.ost-menu { display: flex; flex-direction: column; border-bottom: 1px solid var(--border-color, rgba(128,128,128,.2)); }
.ost-menu-row { position: relative; display: flex; align-items: center; gap: 10px; min-height: 48px; padding: 0 16px; border: none; background: none; color: inherit; text-align: left; cursor: pointer; overflow: hidden; }
.ost-burn-bar { position: absolute; left: 0; bottom: 0; height: 3px; background: var(--warning-color, #f59e0b); transition: width .05s linear; }
.ost-request, .ost-pushcard { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-bottom: 1px solid var(--border-color, rgba(128,128,128,.2)); font-size: .85rem; flex-wrap: wrap; }
.ost-request p { margin: 0; flex: 1 1 100%; }
.ost-req-btns { display: flex; gap: 8px; }
.ost-push-dismiss { min-width: 44px; min-height: 44px; border: none; background: none; color: inherit; margin-left: auto; }
.ost-pushmsg { font-size: .78rem; opacity: .75; padding: 4px 14px; margin: 0; }
/* §CHATPOLISH — the load-failure row: the list view's `.os-err` idiom, in the
   thread's own class prefix. */
.ost-loaderr { display: flex; align-items: center; gap: 8px; margin: 10px 12px 2px; padding: 10px 12px; border-radius: 10px; border: 1px solid var(--warning-color, #f59e0b); background: rgba(245, 158, 11, .06); }
.ost-loaderr-body { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
.ost-loaderr-title { font-weight: 600; }
.ost-loaderr-why { font-size: .78rem; opacity: .7; overflow: hidden; text-overflow: ellipsis; }
.ost-loaderr-btn { min-height: 36px; padding: 0 12px; border-radius: 8px; border: 1px solid var(--border-color, rgba(128,128,128,.3)); background: none; color: inherit; font-weight: 600; cursor: pointer; flex: 0 0 auto; }
/* §CHATPOLISH — `.ost-assistant` was declared on the assistant banner and had no
   rule anywhere, so "@assistant is in this room" rendered pixel-identical to the
   public-transparency banner it sits under. Two different disclosures reading as
   one is the thing the visible-presence law exists to prevent. */
.ost-assistant { border-left: 2px solid rgba(79, 216, 196, .55); padding-left: 10px; }
.ost-scroll { flex: 1; min-height: 0; overflow-y: auto; padding: 12px 12px 8px; display: flex; flex-direction: column; gap: 6px; }
.ost-older { align-self: center; min-height: 44px; padding: 0 16px; border-radius: 999px; border: 1px dashed var(--border-color, rgba(128,128,128,.3)); background: none; color: inherit; font-size: .8rem; }
.ost-author { margin-top: 8px; }
/* §DEALTHREADS — a rail speaking (system sender): labelled as machinery, not a person */
.ost-rail-author { display: inline-flex; align-items: center; gap: 5px; font-size: .68rem; font-weight: 600; letter-spacing: .04em; opacity: .55; }
.ost-rail-author :deep(svg) { width: .8rem; height: .8rem; }
/* §ROOMVIEW — this chip sat at flex-start whatever it introduced, so YOUR OWN
   name appeared on the far left above a bubble on the far right. It follows the
   message now. */
.ost-author.mine { align-self: flex-end; }

/* §ROOMVIEW — `.ost-hosting` and `.ost-hosting-timer` had MARKUP AND NO CSS
   ANYWHERE IN THE TREE, so the honest hosting line rendered as full-bleed
   body-size text with the server glyph jammed against the first word. It is the
   loudest thing on the screen and it is meant to be the quietest. Same caption
   idiom as `.ost-sys-row` / `.ost-me-row` a few rules down. */
.ost-hosting {
  display: flex; align-items: center; gap: 6px;
  padding: 7px 12px;
  font-size: .74rem; line-height: 1.35; opacity: .6;
  border-bottom: 1px solid var(--border-color, rgba(128, 128, 128, .16));
}
.ost-hosting :deep(svg) { flex: none; width: 13px; height: 13px; opacity: .9; }
.ost-privacy-list { list-style: none; margin: 0 0 10px; padding: 0; display: flex;
  flex-direction: column; gap: 10px; }
.ost-privacy-list li { display: flex; gap: 8px; align-items: flex-start;
  font-size: 0.82rem; line-height: 1.45; color: var(--nc-text-secondary, #9aa4b2); }
.ost-privacy-list li svg { flex: 0 0 auto; margin-top: 2px; }

.ost-hosting-timer { white-space: nowrap; opacity: .85; }
/* §OCOPTIN transparency banner — same quiet strip family as .ost-hosting */
.ost-transparency {
  display: flex; align-items: center; gap: 6px; padding: 4px 12px;
  font-size: .72rem; color: var(--primary-color, #4fd8c4); opacity: .9;
  border-bottom: 1px solid var(--border-color, rgba(128,128,128,.15));
}
.ost-transparency :deep(svg) { flex: none; width: 13px; height: 13px; }

/* §ROOMVIEW DESKTOP — this view is Pocket-shaped and was the ONLY OurChat
   surface, so on a 1440px screen a one-line message stretched the full width:
   ~200 characters per line against the ~65 that is readable, with a thousand
   pixels of dead space between the sender's name on the left and their own
   bubble on the right. Nothing here changes below 900px, so the phone layout
   and every Pocket battery are untouched — the column is simply capped and
   centred once there is room to do it. */
@media (min-width: 900px) {
  .ost { --ost-col: 760px; --ost-msg: min(76%, 578px); }
  /* V0652 (ad): the console's chat widens the column to a readable maximum, about 110 characters of message text a
     line (his "the chat is very narrow it has a lot of space on the sides"; measured: 68rem of bubble holds 110 of the
     console's characters); Pocket keeps its own column. */
  .ost--desk { --ost-col: 78rem; --ost-msg: min(88%, 68rem); }
  .ost-scroll > * { width: 100%; max-width: var(--ost-col); margin-left: auto; margin-right: auto; }
  .ost-scroll > .ost-msg { max-width: var(--ost-msg); }
  .ost-scroll > .ost-msg.mine { margin-right: max(0px, calc((100% - var(--ost-col)) / 2)); }
  .ost-scroll > .ost-msg:not(.mine):not(.sys) { margin-left: max(0px, calc((100% - var(--ost-col)) / 2)); }
  /* The author chip must SHRINK to its content, or `width:100%` above makes it
     a 760px box whose chip sits at the box's left edge — which reads as the name
     floating in the middle of the column, detached from the bubble it labels. */
  .ost-scroll > .ost-author { width: auto; max-width: var(--ost-col); }
  .ost-scroll > .ost-author.mine { margin-left: auto; margin-right: max(0px, calc((100% - var(--ost-col)) / 2)); }
  .ost-scroll > .ost-author:not(.mine) { margin-right: auto; margin-left: max(0px, calc((100% - var(--ost-col)) / 2)); }
  /* V0652 (ac): a thread's bar hugs its words and sits under its root, on its side of the column */
  .ost-scroll > .ost-thread-bar { width: auto; max-width: var(--ost-col); }
  .ost-scroll > .ost-thread-bar.mine { margin-left: auto; margin-right: max(0px, calc((100% - var(--ost-col)) / 2)); }
  .ost-scroll > .ost-thread-bar:not(.mine) { margin-right: auto; margin-left: max(0px, calc((100% - var(--ost-col)) / 2)); }
  /* V0654 (ap): your request to your assistant hugs its words on your side of the column, like your own lines */
  .ost-scroll > .caa { width: auto; max-width: var(--ost-msg); margin-left: auto; margin-right: max(0px, calc((100% - var(--ost-col)) / 2)); }
  .ost-composer { max-width: calc(var(--ost-col) + 24px); margin: 0 auto; width: 100%; }
  .ost-hosting { justify-content: center; }
}
.ost-msg { display: flex; max-width: 86%; align-self: flex-start; }
.ost-msg.mine { align-self: flex-end; }
/* V0652 (ac): a thread's messages, opened under their root: indented on a hairline */
.ost-msg.in-thread { margin-left: 18px; padding-left: 10px; border-left: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), .35); }
.ost-thread-bar { align-self: flex-start; display: inline-flex; flex-wrap: wrap; align-items: center; gap: 4px 10px; min-height: 34px;
  margin: 2px 0 4px; padding: 4px 10px; border: 1px solid var(--nc-border-strong, #343a4d); border-radius: 8px; background: none;
  color: inherit; font-size: .76rem; cursor: pointer; text-align: left; }
.ost-thread-bar.mine { align-self: flex-end; }
.ost-thread-bar.open { border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), .55); }
.ost-thread-count { font-weight: 600; }
.ost-thread-new { font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .66rem; letter-spacing: .08em; color: var(--nc-primary, #00d2d2); }
.ost-thread-forme { font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .66rem; letter-spacing: .08em; color: var(--warning-color, #f59e0b); }
.ost-thread-last { color: #8b96a5; }
.ost-thread-act { color: var(--nc-primary, #00d2d2); }
@media (pointer: coarse) { .ost-thread-bar { min-height: 44px; } }
/* V0653 (al): the side panel's WAITING ON YOU, a count and a door to the list pinned above the history */
.ost-side-note { margin: 0; font-size: .8rem; color: #8b96a5; }
.ost-side-link { margin-top: 6px; min-height: 36px; padding: 0 10px; border-radius: 8px; cursor: pointer; font: inherit; font-size: .8rem;
  background: none; color: var(--nc-primary, #00d2d2); border: 1px solid var(--nc-border, rgba(255, 255, 255, 0.3)); }
.ost-reply-btn { align-self: flex-end; margin-left: 6px; min-height: 24px; padding: 0 6px; border: 0; border-radius: 6px; background: none;
  color: #8b96a5; font-size: .68rem; cursor: pointer; opacity: 0; transition: opacity .12s; }
.ost-msg:hover .ost-reply-btn, .ost-reply-btn:focus-visible { opacity: 1; }
@media (hover: none) { .ost-reply-btn { opacity: .7; min-height: 36px; } }
.ost-replying { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; padding: 4px 8px; border-left: 2px solid var(--nc-primary, #00d2d2);
  border-radius: 4px; background: rgba(var(--nc-primary-rgb, 0, 210, 210), .06); font-size: .76rem; }
.ost-replying-tx { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #c4ccd6; }
.ost-replying-x { flex: none; display: grid; place-items: center; width: 28px; height: 28px; border: 0; background: none; color: inherit; cursor: pointer; }
.ost-replying-x :deep(svg) { width: 14px; height: 14px; }
.ost-msg.sys { align-self: center; }
/* V0652 (ag): the first unread line and the live mark (the design's hairline and shape language, (ak)) */
.ost-unread { display: flex; align-items: center; gap: 10px; margin: 10px 0 2px; }
.ost-unread::before { content: ''; flex: 1; border-top: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), .55); }
.ost-unread span { font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .66rem; letter-spacing: .14em; color: var(--nc-primary, #00d2d2); }
.ost-live { display: inline-flex; align-items: center; gap: 6px; font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .66rem; letter-spacing: .1em; text-transform: uppercase; opacity: .75; white-space: nowrap; }
.ost-live i { width: 7px; height: 7px; border-radius: 50%; border: 1px solid var(--nc-primary, #00d2d2); background: var(--nc-primary, #00d2d2); display: inline-block; }
.ost-live[data-state="catching_up"] i { background: linear-gradient(90deg, var(--nc-primary, #00d2d2) 50%, transparent 50%); }
.ost-live[data-state="offline"] i { background: transparent; border-color: currentColor; }
.ost-bubble { padding: 9px 13px; border-radius: 16px; background: var(--surface-2, rgba(128,128,128,.12)); white-space: pre-wrap; word-break: break-word; }
/* V0652 (x): a rendered message wraps as markdown (its line breaks are <br>, so pre-wrap would double them) */
.ost-bubble.ost-md { white-space: normal; overflow-wrap: anywhere; }
.ost-msg { position: relative; flex-wrap: wrap; }
.ost-time {
  flex-basis: 100%; margin: 2px 6px 0; font-family: var(--font-mono, 'IBM Plex Mono', monospace); font-size: .68rem;
  letter-spacing: .04em; color: #8b96a5; cursor: pointer;   /* 4.5:1 on the dark surface at this size */
}
.ost-msg.mine .ost-time { text-align: right; }
/* V0653 (al): under a thread's root drawn at its latest reply, the line that says when that reply came */
.ost-time-last { margin-top: 0; cursor: default; }
.ost-by-key {   /* V0653 (w): the time's type and colour (4.5:1 on the dark surface at this size) */
  flex-basis: 100%; margin: 0 6px; font-size: .68rem; font-style: italic; color: #8b96a5;
}
.ost-msg.mine .ost-by-key { text-align: right; }
/* V0654 (ap): the assistant's amber: its line's mark, the chip while it is on, the switch */
.ost-by-assistant { color: var(--warning-color, #f59e0b); font-style: normal; }
.ost-by-assistant-mark { width: 12px; height: 12px; margin-right: 4px; vertical-align: -2px; }
.ost-speaker.assist { border-color: var(--warning-color, #f59e0b); background: rgba(245, 158, 11, .14); color: var(--warning-color, #f59e0b); }
.ost-speaker-assist { width: 15px; height: 15px; flex: none; }
.ost-assist-row { margin: 8px 0 4px; }
.ost-assist-switch { display: flex; align-items: center; gap: 8px; width: 100%; min-height: 44px; padding: 0 12px; border-radius: 10px;
  border: 1px solid var(--border-color, rgba(128,128,128,.3)); background: none; color: inherit; cursor: pointer; text-align: left; }
.ost-assist-switch.on { border-color: var(--warning-color, #f59e0b); background: rgba(245, 158, 11, .12); }
.ost-assist-switch-mark { width: 16px; height: 16px; flex: none; color: var(--warning-color, #f59e0b); }
.ost-assist-switch-label { flex: 1; min-width: 0; font-weight: 600; font-size: .85rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ost-assist-switch-state { font-size: .72rem; text-transform: uppercase; letter-spacing: .04em; opacity: .8; }
.ost-assist-switch.on .ost-assist-switch-state { color: var(--warning-color, #f59e0b); opacity: 1; }
.ost-msg.for-me .ost-bubble, .ost-msg.ask { box-shadow: inset 3px 0 0 var(--primary-color, #4fd8c4); }
.ost-msg.for-me .ost-bubble { background: rgba(79, 216, 196, .1); }
.ost-forme-toggle {
  align-self: center; margin: 4px 0 8px; padding: 4px 12px; border-radius: 999px; cursor: pointer;
  border: 1px solid var(--primary-color, #4fd8c4); background: none; color: var(--primary-color, #4fd8c4);
  font-family: var(--font-mono, 'IBM Plex Mono', monospace); font-size: .72rem; letter-spacing: .06em;
}
.ost-forme-toggle.on { background: var(--primary-color, #4fd8c4); color: #06211d; }
.mine .ost-bubble { background: var(--primary-soft, rgba(79,216,196,.18)); }
.ost-tombstone, .ost-ping-row, .ost-me-row { font-size: .8rem; opacity: .6; display: inline-flex; align-items: center; gap: 6px; }
.ost-me-row { font-style: italic; opacity: .85; }
.ost-calling { display: flex; align-items: center; gap: 8px; align-self: center; font-size: .8rem; opacity: .7; padding: 6px 0; }
.ost-composer { display: flex; align-items: flex-end; gap: 8px; padding: 8px 10px calc(8px + env(safe-area-inset-bottom)); border-top: 1px solid var(--border-color, rgba(128,128,128,.2)); }
.ost-speaker { display: inline-flex; align-items: center; gap: 6px; min-height: 44px; max-width: 130px; padding: 0 10px; border-radius: 999px; border: 1px solid var(--border-color, rgba(128,128,128,.3)); background: none; color: inherit; cursor: pointer; }
.ost-speaker-name { font-size: .75rem; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ost-speaker-as { font-size: .68rem; opacity: .7; }
/* V0652 (aj): a phone-width pane gives the message field the room: the chip keeps its icon and the name, not the "as" */
.ost--narrow .ost-speaker { gap: 4px; padding: 0 8px; max-width: 104px; }
.ost--narrow .ost-speaker-as { display: none; }
.ost-by-owner { font-size: .68rem; opacity: .7; margin-left: 6px; font-style: italic; }
/* V0654 (aq): a member's wake mode in the member sheet */
.ost-member-wake { margin-top: 4px; }
.ost-wake-chip { font-size: .68rem; padding: 1px 8px; border-radius: 999px; border: 1px solid var(--border-color, rgba(128,128,128,.3)); opacity: .85; }
.ost-input-wrap { flex: 1; min-width: 0; position: relative; }
.ost-hint { font-size: .78rem; opacity: .85; padding: 4px 2px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ost-hint-send { min-height: 32px; border: none; background: none; color: var(--primary-color, #4fd8c4); font-weight: 600; cursor: pointer; }
.ost-complete { position: absolute; bottom: 100%; left: 0; right: 0; background: var(--surface-1, #16181d); border: 1px solid var(--border-color, rgba(128,128,128,.3)); border-radius: 10px; overflow: hidden; z-index: 5; }
.ost-complete-row { display: flex; flex-direction: column; align-items: flex-start; width: 100%; min-height: 44px; padding: 6px 12px; border: none; background: none; color: inherit; text-align: left; cursor: pointer; }
.ost-complete-cmd { font-family: monospace; font-size: .82rem; }
.ost-complete-gloss { font-size: .72rem; opacity: .6; }

/* §OURSTATE-7 C — the name-completion list, same anchoring as the command one. */
.ost-suggest { max-height: 46vh; overflow-y: auto; }
.ost-suggest-note { margin: 0; padding: 10px 12px; font-size: .78rem; opacity: .65; }
.ost-suggest-err { color: var(--danger-color, #e0716b); opacity: .95; }
.ost-suggest-row { display: flex; align-items: center; gap: 16px; width: 100%; min-height: 48px;
  padding: 6px 10px; border: none; background: none; color: inherit; text-align: left; cursor: pointer; }
.ost-suggest-row:disabled { opacity: .5; }
.ost-suggest-body { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.ost-suggest-name { font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ost-suggest-price { font-size: .72rem; opacity: .6; }
.ost-suggest-go { opacity: .5; flex: none; }

/* §OURSTATE-7 B — /help. The colour per group is the group's RULE made
   visible; it is set from the declared `group` field, never per command. */
.ost-help-group { border-left: 3px solid var(--border-color, rgba(128,128,128,.3));
  padding-left: 10px; display: flex; flex-direction: column; gap: 2px; }
.ost-help-any   { border-left-color: var(--border-color, rgba(128,128,128,.45)); }
.ost-help-agent { border-left-color: var(--primary-color, #4fd8c4); }
.ost-help-room  { border-left-color: var(--warning-color, #f59e0b); }
.ost-help-op    { border-left-color: var(--danger-color, #e0716b); }
.ost-help-head { margin: 0; font-size: .74rem; font-weight: 800; text-transform: uppercase; letter-spacing: .06em; }
/* §CHATCOHERE A4 — the fold. Reads as a quiet link, not a button competing with
   the commands themselves. */
.ost-help-more { display: block; width: 100%; text-align: left; background: none; border: 0;
  padding: 4px 0; font-size: .78rem; opacity: .6; cursor: pointer; color: inherit; }
.ost-help-more:hover { opacity: .9; text-decoration: underline; }
.ost-help-any   .ost-help-head { color: inherit; opacity: .75; }
.ost-help-agent .ost-help-head { color: var(--primary-color, #4fd8c4); }
.ost-help-room  .ost-help-head { color: var(--warning-color, #f59e0b); }
.ost-help-op    .ost-help-head { color: var(--danger-color, #e0716b); }
.ost-help-rule { margin: 0 0 4px; font-size: .72rem; opacity: .6; }
.ost-help-row { display: flex; flex-direction: column; align-items: flex-start; gap: 1px;
  width: 100%; min-height: 44px; padding: 5px 6px; border: none; background: none;
  color: inherit; text-align: left; cursor: pointer; border-radius: 8px; }
.ost-help-row.off { opacity: .42; cursor: default; }
.ost-help-cmd { font-family: monospace; font-size: .8rem; }
.ost-help-gloss { font-size: .72rem; opacity: .65; }
.ost-help-why { font-size: .68rem; font-style: italic; opacity: .85; }

/* §OURSTATE-7 D — the ticket bar. */
.ost-support-bar { display: flex; align-items: baseline; flex-wrap: wrap; gap: 6px;
  padding: 6px 12px; font-size: .74rem;
  border-bottom: 1px solid var(--border-color, rgba(128,128,128,.15)); }
.ost-support-note { opacity: .55; }
.ost-support-err { color: var(--danger-color, #e0716b); }
.ost-input { width: 100%; min-height: 44px; max-height: 120px; padding: 11px 12px; border-radius: 12px; border: 1px solid var(--border-color, rgba(128,128,128,.3)); background: none; color: inherit; font: inherit; font-size: 16px; resize: none; }
.ost-send { min-width: 44px; min-height: 44px; border-radius: 12px; border: none; background: var(--primary-color, #4fd8c4); color: #06211d; display: grid; place-items: center; cursor: pointer; }
.ost-send:disabled { opacity: .4; }
.ost-sheet-veil { position: fixed; inset: 0; background: rgba(0,0,0,.5); display: flex; align-items: flex-end; justify-content: center; z-index: 60; }
.ost-sheet { width: 100%; max-width: 480px; max-height: 82vh; overflow-y: auto; background: var(--surface-1, #16181d); border-radius: 16px 16px 0 0; padding: 16px 16px calc(16px + env(safe-area-inset-bottom)); display: flex; flex-direction: column; gap: 10px; }
/* §FINDFIX — ALL 15 thread sheets ride this one pair: on desktop they become
   centered dialogs above the shell chrome (sidebar z-index 10000); the phone
   bottom sheet below the breakpoint is byte-identical. */
@media (min-width: 900px) {
  .ost-sheet-veil { align-items: center; padding: 32px; z-index: 10500; }
  .ost-sheet { max-height: min(80vh, 760px); border-radius: 16px; padding-bottom: 18px;
               border: 1px solid var(--border-color, rgba(128,128,128,.25));
               box-shadow: 0 24px 64px rgba(0,0,0,.55); }
}
.ost-sheet h3 { margin: 0; }
.ost-sheet-ask { margin: 0; font-size: .95rem; }
.ost-sheet-price { margin: 0; font-weight: 600; font-variant-numeric: tabular-nums; }
.ost-sheet-refuse { margin: 0; color: var(--warning-color, #f59e0b); font-size: .85rem; }
/* §CHATCOHERE D4 — what you hold, stated beside what it costs. Quiet by default;
   the shortfall clause is the only part that raises its voice, and only when BOTH
   numbers were readable. */
.ost-sheet-held { margin: 0 0 6px; font-size: .85rem; opacity: .8; }
.ost-sheet-short { color: var(--warning-color, #f59e0b); opacity: 1; }
.ost-sheet-door { display: inline-block; margin: 0 0 10px; font-size: .85rem; font-weight: 600; color: var(--accent-color, #22d3ee); text-decoration: none; }
.ost-sheet-door:hover { text-decoration: underline; }
.ost-sheet-btns { display: flex; gap: 8px; justify-content: flex-end; }
/* §DEALTHREADS — the proposal composer */
.ost-sheet-input { width: 100%; min-height: 44px; padding: 10px 12px; border-radius: 10px; border: 1px solid var(--border-color, rgba(128,128,128,.3)); background: none; color: inherit; font: inherit; font-size: 16px; }
textarea.ost-sheet-input { resize: vertical; }
.ost-propose-row { display: flex; align-items: center; gap: 8px; }
.ost-propose-num { flex: 1; min-width: 0; }
.ost-propose-ccy { font-size: .8rem; opacity: .6; font-weight: 600; }
.ost-btn { min-height: 44px; padding: 0 18px; border-radius: 10px; border: 1px solid var(--border-color, rgba(128,128,128,.3)); background: none; color: inherit; font-weight: 600; cursor: pointer; }
.ost-accept { background: var(--primary-color, #4fd8c4); color: #06211d; border-color: transparent; }
/* §ONBOARDQOL P2 — a disabled Call must LOOK disabled: the DOM said disabled=true while the
   button painted the same bright green as an enabled one (read off the screenshot, not the DOM). */
.ost-accept:disabled, .ost-btn:disabled { opacity: .4; cursor: not-allowed; filter: saturate(.4); }
.ost-danger { background: var(--warning-color, #f59e0b); color: #1a1206; border-color: transparent; }
.ost-audit-note { font-size: .75rem; opacity: .6; margin: 0; }
/* §ORGPOCKET polish (2026-08-28) — eight classes in this file carried markup and
   NO rule that could reach them, the same defect §ROOMVIEW found in `.ost-hosting`.
   Two of them changed MEANING rather than looks:
     · `.ost-timer-on` marks the SELECTED disappearing-messages interval, so with
       no rule the sheet showed four identical buttons and never said which one
       is in force — a setting you cannot read is a setting you cannot trust.
     · `.ost-burn` is the row that BURNS a thread. It painted exactly like the
       neutral rows above it. Same class as the org dashboard's remove-member
       button carrying `.cmd-btn--danger` with no such rule. */
.ost-timer-on { background: var(--primary-color, #4fd8c4); color: #06211d; border-color: transparent; }
.ost-burn { color: var(--warning-color, #f59e0b); }
.ost-menu-val { margin-left: auto; font-size: .78rem; opacity: .6; font-variant-numeric: tabular-nums; }
.ost-who-loading { opacity: .45; letter-spacing: .12em; }
.ost-authority { padding: 8px 0 2px; border-top: 1px solid var(--border-color, rgba(128,128,128,.12)); }
.ost-auth-line { margin: 0; font-size: .78rem; line-height: 1.55; opacity: .75; }
.ost-help { gap: 12px; line-height: 1.55; }
.ost-ledger-open { margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--border-color, rgba(128,128,128,.12)); }
/* §OURSTATE-2 room chrome */
.ost-room-head { display: flex; flex-direction: column; min-width: 0; }
.ost-room-title { font-weight: 700; display: inline-flex; align-items: center; gap: 6px; }
.ost-room-topic { font-size: .75rem; opacity: .6; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ost-announce { font-size: .62rem; text-transform: uppercase; letter-spacing: .05em; border: 1px solid var(--warning-color, #f59e0b); color: var(--warning-color, #f59e0b); border-radius: 6px; padding: 0 5px; }
.ost-genesis { border-bottom: 1px solid var(--border-color, rgba(128,128,128,.2)); }
.ost-genesis-head { display: flex; align-items: center; gap: 8px; width: 100%; min-height: 44px; padding: 6px 14px; border: none; background: none; color: inherit; text-align: left; cursor: pointer; }
.ost-genesis-line { flex: 1; min-width: 0; font-size: .82rem; font-style: italic; opacity: .85; white-space: pre-wrap; }
.ost-genesis-line.clamp { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ost-genesis-body { padding: 0 14px 10px 38px; display: flex; flex-direction: column; gap: 4px; }
.ost-genesis-reg { margin: 0; font-size: .72rem; opacity: .6; }
.ost-genesis-enf { opacity: .8; }
.ost-genesis-meta { margin: 0; font-size: .68rem; opacity: .45; }
/* §TWOAGENT G1's visible join (V0437) named classes no rule defined: its question and buttons drew as bare text.
   It is the request banner's shape (the same buttons), at the foot of the thread like the room gate. */
.ost-joingate { display: flex; align-items: center; gap: 8px 10px; flex-wrap: wrap; padding: 12px 14px; border-top: 1px solid var(--border-color, rgba(128,128,128,.2)); font-size: .85rem; }
.ost-joingate-title { margin: 0; flex: 1 1 100%; font-weight: 600; }
.ost-joingate-body { margin: 0; flex: 1 1 100%; line-height: 1.45; opacity: .85; }
.ost-roomgate { display: flex; align-items: center; gap: 8px; padding: 12px 14px calc(12px + env(safe-area-inset-bottom)); border-top: 1px solid var(--border-color, rgba(128,128,128,.2)); font-size: .85rem; opacity: .85; }
.ost-sys-row { font-size: .8rem; opacity: .7; display: inline-flex; align-items: center; gap: 6px; }
.ost-member-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-height: 48px; border-bottom: 1px solid var(--border-color, rgba(128,128,128,.12)); }
.ost-member-name { display: inline-flex; align-items: center; gap: 6px; font-weight: 600; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.ost-role { font-size: .62rem; text-transform: uppercase; letter-spacing: .05em; border: 1px solid var(--border-color, rgba(128,128,128,.35)); border-radius: 6px; padding: 0 5px; opacity: .75; }
.ost-mutedico { opacity: .5; width: 14px; height: 14px; }
.ost-member-ops { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
.ost-chipbtn { min-height: 34px; padding: 0 10px; border-radius: 8px; border: 1px solid var(--border-color, rgba(128,128,128,.3)); background: none; color: inherit; font-size: .74rem; font-weight: 600; cursor: pointer; }
.ost-chipbtn.danger { border-color: var(--warning-color, #f59e0b); color: var(--warning-color, #f59e0b); }
.ost-hold { position: relative; overflow: hidden; }
.ost-ledger-line { display: flex; align-items: center; gap: 10px; min-height: 44px; border-bottom: 1px solid var(--border-color, rgba(128,128,128,.12)); }
.ost-stock-line { font-family: ui-monospace, monospace; font-size: 12px; line-height: 1.7;
  color: var(--nc-text, #e6edf3); word-break: break-word; font-variant-numeric: tabular-nums; }
.ost-ledger-ccy { font-weight: 700; min-width: 48px; }
.ost-ledger-nums { flex: 1; display: flex; flex-direction: column; font-size: .74rem; opacity: .7; font-variant-numeric: tabular-nums; }
.ost-ledger-net { font-weight: 700; font-variant-numeric: tabular-nums; }
.ost-ledger-net.pos { color: var(--success-color, #4ade80); }
.ost-ledger-net.neg { color: var(--warning-color, #f59e0b); }
.ost-ledger-openhead { font-size: .7rem; text-transform: uppercase; letter-spacing: .06em; opacity: .55; margin: 8px 0 2px; }
.ost-ledger-openrow { display: flex; justify-content: space-between; gap: 8px; font-size: .8rem; padding: 3px 0; }
.ost-ledger-openamt { font-variant-numeric: tabular-nums; opacity: .8; }
.ost-workrow { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; width: 100%; min-height: 52px; padding: 8px 6px; border: none; background: none; color: inherit; text-align: left; border-bottom: 1px solid var(--border-color, rgba(128,128,128,.12)); cursor: pointer; }
.ost-speakrow { display: flex; align-items: center; gap: 8px; width: 100%; min-height: 48px; padding: 0 10px; border: 1px solid transparent; border-radius: 10px; background: none; color: inherit; text-align: left; cursor: pointer; }
.ost-speakrow.on { border-color: var(--primary-color, #4fd8c4); }
.ost-workrow-title { font-weight: 600; }
.ost-workrow-meta { display: flex; gap: 8px; font-size: .72rem; opacity: .6; }
.pk-ptr-spin { animation: ost-spin 1s linear infinite; }
@keyframes ost-spin { to { transform: rotate(360deg); } }
.ost-here-row { display: flex; align-items: center; gap: 10px; min-height: 44px; }
.ost-here-note { font-size: .78rem; opacity: .6; margin-left: auto; }
.ost-linkish { border: none; background: none; padding: 0 0 0 4px; color: var(--accent, #4da3ff);
  text-decoration: underline; cursor: pointer; font: inherit; }

/* §CHATDESK C4 — consent banner + attach flow */
.ost-review-banner { display: flex; align-items: center; gap: 8px; padding: 6px 12px;
  font-size: .76rem; background: color-mix(in srgb, currentColor 7%, transparent);
  border-bottom: 1px solid var(--border-color, rgba(128,128,128,.2)); opacity: .9; }
.ost-review-revoke { margin-left: auto; font-size: .72rem; padding: 2px 10px; border-radius: 7px;
  border: 1px solid currentColor; background: transparent; color: inherit; cursor: pointer; }
.ost-review-attach { padding: 6px 12px; font-size: .78rem;
  border-bottom: 1px solid var(--border-color, rgba(128,128,128,.2)); }
.ost-review-attach > summary { cursor: pointer; opacity: .8; }
.ost-review-note { opacity: .65; margin: 6px 0; }
.ost-review-row { display: flex; gap: 8px; align-items: center; }
.ost-review-select { flex: 1; font-size: .78rem; padding: 4px 8px; border-radius: 7px;
  border: 1px solid var(--border-color, rgba(128,128,128,.35)); background: transparent; color: inherit; }
.ost-review-grant { font-size: .74rem; padding: 4px 12px; border-radius: 7px;
  border: 1px solid currentColor; background: transparent; color: inherit; cursor: pointer; }
.ost-review-grant:disabled { opacity: .45; }
.ost-review-msg { margin: 6px 0 0; opacity: .8; }
</style>
