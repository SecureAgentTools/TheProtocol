<template>
  <div class="fk" data-testid="fk-root" :data-state="viewState">
    <div class="fk-wrap">
      <p v-if="loading" class="fk-quiet" role="status">{{ t('frameKitView.loading', 'Reading your frame…') }}</p>

      <section v-else-if="off" class="fk-empty" data-testid="fk-off">
        <h1 class="fk-empty-title">{{ t('frameKitView.off.title', 'Frame kits are not offered here') }}</h1>
        <p class="fk-empty-lead">{{ t('frameKitView.off.lead', 'This frame does not hand out the frame kit. Ask the network you applied to.') }}</p>
      </section>

      <section v-else-if="loadError" class="fk-empty" data-testid="fk-error">
        <h1 class="fk-empty-title">{{ t('frameKitView.error.title', 'Your frame page did not load') }}</h1>
        <p class="fk-empty-lead">{{ loadError }}</p>
        <button type="button" class="fk-btn" @click="load">
          <Icon name="mdi:refresh" class="fk-btn-icon" />{{ t('frameKitView.error.retry', 'Try again') }}
        </button>
      </section>

      <section v-else-if="!current" class="fk-empty" data-testid="fk-empty">
        <h1 class="fk-empty-title">{{ t('frameKitView.empty.title', 'You have not asked for a frame yet') }}</h1>
        <p class="fk-empty-lead">{{ t('frameKitView.empty.lead', 'A frame is your own registry, ledger and identity root, federated with the network. Ask for one, and this page follows your request from review to a running frame.') }}</p>
        <router-link to="/frame-commander" class="fk-btn fk-btn--primary" data-testid="fk-request">
          {{ t('frameKitView.empty.cta', 'Request a frame') }}
        </router-link>
      </section>

      <template v-else>
        <header class="fk-hero">
          <p class="fk-context">
            {{ contextName }}
            <span v-if="hostingLabel" class="fk-hosting">{{ hostingLabel }}</span>
          </p>
          <h1 class="fk-host" data-testid="fk-host"><template v-for="(part, pi) in addressParts" :key="pi"><span class="fk-host-part">{{ part }}</span><wbr v-if="pi < addressParts.length - 1" /></template></h1>
          <p class="fk-lede" data-testid="fk-lede" :data-tone="ledeTone">{{ lede }}</p>
          <router-link v-if="declined" to="/frame-commander" class="fk-btn fk-lede-cta" data-testid="fk-ask-again">
            {{ t('frameKitView.empty.cta', 'Request a frame') }}
          </router-link>
          <dl class="fk-facts">
            <div v-if="current.trust_domain" class="fk-fact">
              <dt>{{ t('frameKitView.facts.trustDomain', 'Trust domain') }}</dt>
              <dd>spiffe://{{ current.trust_domain }}</dd>
            </div>
            <div v-if="current.ticker" class="fk-fact">
              <dt>{{ t('frameKitView.facts.currency', 'Currency') }}</dt>
              <dd>{{ current.ticker }}<span v-if="current.currency_name" class="fk-fact-soft">{{ current.currency_name }}</span></dd>
            </div>
            <div v-if="current.location" class="fk-fact">
              <dt>{{ t('frameKitView.facts.location', 'Location') }}</dt>
              <dd class="fk-fact-plain">{{ current.location }}</dd>
            </div>
            <div class="fk-fact">
              <dt>{{ t('frameKitView.facts.requested', 'Requested') }}</dt>
              <dd class="fk-fact-plain">{{ fmtDate(current.created_at) }}</dd>
            </div>
          </dl>
        </header>

        <div class="fk-grid">
          <aside class="fk-aside" :aria-label="t('frameKitView.kit.region', 'Frame kit')">
            <div v-if="selfHosted" class="fk-kit" data-testid="fk-kit" :data-kit="kit?.state">
              <svg viewBox="0 0 200 200" class="fk-seal" :class="{ 'fk-seal--live': ready, 'fk-seal--empty': !ticks.length }"
                   role="img" :aria-label="sealLabel">
                <circle cx="100" cy="100" r="54" class="fk-seal-ring" />
                <circle cx="100" cy="100" r="92" class="fk-seal-halo" />
                <g class="fk-seal-ticks">
                  <line v-for="(tk, i) in ticks" :key="i" x1="100" y1="41" x2="100" :y2="41 - tk.length"
                        :transform="`rotate(${tk.angle} 100 100)`"
                        :style="{ '--o': ready ? tk.opacity : 0.18, '--len': tk.length, '--i': i }" />
                </g>
                <text x="100" y="99" text-anchor="middle" class="fk-seal-ticker">{{ sealTicker }}</text>
                <text x="100" y="119" text-anchor="middle" class="fk-seal-caption">{{ sealCaption }}</text>
              </svg>

              <h2 class="fk-kit-title">{{ t('frameKitView.kit.title', 'Frame kit') }}</h2>
              <p v-if="release" class="fk-kit-meta" data-testid="fk-release">
                {{ tp('frameKitView.kit.release', 'Release {version}, {size}', { version: release.version || '?', size: formatBytes(release.size_bytes, locale) }) }}
              </p>
              <p v-else class="fk-kit-meta">{{ t('frameKitView.kit.noRelease', 'No kit is published on this frame yet.') }}</p>

              <button type="button" class="fk-btn fk-btn--primary fk-btn--wide" data-testid="fk-download"
                      :disabled="!ready || downloading" :aria-describedby="ready ? 'fk-window' : 'fk-closed'" @click="download">
                <Icon :name="ready ? 'mdi:download' : 'mdi:lock'" class="fk-btn-icon" />
                {{ downloading ? t('frameKitView.kit.preparing', 'Preparing your download…') : t('frameKitView.kit.download', 'Download the kit') }}
              </button>
              <p v-if="ready" id="fk-window" class="fk-kit-window" data-testid="fk-window">
                <span>{{ tp('frameKitView.kit.left', '{left} of {max} downloads left', { left: downloadsLeft, max: kit?.downloads_max ?? 0 }) }}</span>
                <span v-if="kit?.available_until">{{ tp('frameKitView.kit.until', 'Open until {date}', { date: fmtDate(kit.available_until) }) }}</span>
              </p>
              <p v-else id="fk-closed" class="fk-kit-closed" data-testid="fk-closed">{{ closedSentence }}</p>
              <p v-if="downloadNote" class="fk-kit-note" role="status" data-testid="fk-started">{{ downloadNote }}</p>
              <p v-if="downloadError" class="fk-kit-error" role="alert">{{ downloadError }}</p>

              <div v-if="release && showVerify" class="fk-verify" data-testid="fk-verify">
                <h3 class="fk-verify-title">{{ t('frameKitView.kit.verifyTitle', 'Check the download') }}</h3>
                <p class="fk-verify-lead">{{ t('frameKitView.kit.verifyLead', 'Run this where the file landed. It must print the same sha256 as the seal.') }}</p>
                <div class="fk-cmd fk-cmd--compact">
                  <pre class="fk-pre"><code><span class="fk-line">sha256sum {{ release.filename }}</span></code></pre>
                  <button type="button" class="fk-copy" :aria-label="t('frameKitView.copy.label', 'Copy command')"
                          @click="copy('verify', `sha256sum ${release.filename}`)">
                    <Icon :name="copied === 'verify' ? 'mdi:check' : 'mdi:content-copy'" />
                  </button>
                </div>
                <button type="button" class="fk-sha" data-testid="fk-sha" :title="release.sha256"
                        @click="copy('sha', release.sha256)">
                  <span class="fk-sha-hex"><span v-for="(g, gi) in shaGroups(release.sha256)" :key="gi" class="fk-sha-group">{{ g }}</span></span>
                  <span class="fk-sha-action">
                    <Icon :name="copied === 'sha' ? 'mdi:check' : 'mdi:content-copy'" />
                    {{ copied === 'sha' ? t('frameKitView.copy.done', 'Copied') : t('frameKitView.kit.copySha', 'Copy sha256') }}
                  </span>
                </button>
              </div>
            </div>

            <div v-else class="fk-kit fk-kit--hosted" data-testid="fk-hosted">
              <Icon name="mdi:server-network" class="fk-hosted-icon" />
              <h2 class="fk-kit-title">{{ current.hosting === 'theprotocol' ? t('frameKitView.hosted.title', 'We run this frame for you') : t('frameKitView.unknown.title', 'Where does this frame run?') }}</h2>
              <p class="fk-kit-closed">{{ current.hosting === 'theprotocol'
                ? t('frameKitView.hosted.lead', 'There is nothing to download. We build the frame on our infrastructure and send you its console address when it stands.')
                : t('frameKitView.unknown.lead', 'Your request does not say whether you run the frame yourself. Reply to our mail and we will set it.') }}</p>
            </div>
          </aside>

          <main class="fk-main">
            <section class="fk-section" :aria-labelledby="'fk-progress-title'">
              <h2 id="fk-progress-title" class="fk-h2">{{ t('frameKitView.progress.title', 'Where your frame stands') }}</h2>
              <ol class="fk-track" data-testid="fk-track" :style="{ '--steps': current.progress.length }">
                <li v-for="s in current.progress" :key="s.key" class="fk-track-step" :data-step="s.key" :data-state="s.state"
                    :aria-current="s.state === 'current' ? 'step' : undefined">
                  <span class="fk-track-dot" aria-hidden="true">
                    <Icon v-if="s.state === 'done'" name="mdi:check" />
                    <Icon v-else-if="s.state === 'declined'" name="mdi:close" />
                  </span>
                  <span class="fk-track-label">{{ stepLabel(s.key) }}</span>
                  <span class="fk-track-when">{{ s.at ? fmtDate(s.at) : (s.state === 'current' ? t('frameKitView.progress.next', 'Next') : '') }}</span>
                </li>
              </ol>
            </section>

            <section v-if="selfHosted && !declined" class="fk-section" aria-labelledby="fk-needs-title">
              <div class="fk-section-head">
                <h2 id="fk-needs-title" class="fk-h2">{{ t('frameKitView.needs.title', 'What your host needs') }}</h2>
                <p class="fk-section-lead">{{ t('frameKitView.needs.lead', 'Tick what is ready. This list stays in this browser only.') }}</p>
              </div>
              <ul class="fk-needs" data-testid="fk-needs">
                <li v-for="need in NEEDS" :key="need">
                  <label class="fk-need" :data-done="checked[need] ? '1' : '0'">
                    <input type="checkbox" class="fk-need-box" :checked="!!checked[need]" @change="toggleNeed(need)" />
                    <span class="fk-need-mark" aria-hidden="true"><Icon v-if="checked[need]" name="mdi:check" /></span>
                    <span class="fk-need-text">{{ needLabel(need) }}</span>
                  </label>
                </li>
              </ul>
            </section>

            <section v-if="selfHosted && !declined" class="fk-section" aria-labelledby="fk-steps-title">
              <div class="fk-section-head">
                <h2 id="fk-steps-title" class="fk-h2">{{ t('frameKitView.steps.title', 'Stand it up on your host') }}</h2>
                <p class="fk-section-lead">{{ tp('frameKitView.steps.lead', 'Five steps from the kit to a frame that is part of {network}. Your frame’s values are filled in; the highlighted ones only you know.', { network: networkName }) }}</p>
              </div>
              <ol class="fk-runbook" data-testid="fk-runbook">
                <li v-for="(step, i) in standUp" :key="step.key" class="fk-rb-step" :data-step="step.key">
                  <span class="fk-rb-num" aria-hidden="true">{{ i + 1 }}</span>
                  <div class="fk-rb-body">
                    <h3 class="fk-h3">{{ stepTitle(step.key) }}</h3>
                    <p class="fk-rb-lead">{{ stepLead(step.key) }}</p>
                    <table v-if="step.records" class="fk-dns" data-testid="fk-dns">
                      <thead>
                        <tr>
                          <th scope="col">{{ t('frameKitView.dns.type', 'Type') }}</th>
                          <th scope="col">{{ t('frameKitView.dns.name', 'Name') }}</th>
                          <th scope="col">{{ t('frameKitView.dns.value', 'Points to') }}</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="rec in step.records" :key="rec.name">
                          <td>{{ rec.type }}</td>
                          <td class="fk-dns-name"><template v-for="(part, pi) in hostParts(rec.name)" :key="pi">{{ part }}<wbr v-if="pi < hostParts(rec.name).length - 1" /></template></td>
                          <td><span class="fk-ph">{{ rec.value.text }}</span></td>
                        </tr>
                      </tbody>
                    </table>
                    <div v-for="(cmd, ci) in step.commands" :key="ci" class="fk-cmd" :class="{ 'fk-cmd--script': cmd.script }" :data-testid="`fk-cmd-${step.key}`">
                      <pre class="fk-pre"><code><span v-for="(line, li) in cmd.lines" :key="li" class="fk-line"><template v-for="(tok, ti) in line" :key="ti"><span v-if="tok.placeholder" class="fk-ph">{{ tok.text }}</span><template v-else>{{ tok.text }}</template></template><span v-if="!cmd.script && li < cmd.lines.length - 1" class="fk-cont"> \</span></span></code></pre>
                      <button type="button" class="fk-copy" :aria-label="t('frameKitView.copy.label', 'Copy command')"
                              @click="copy(`${step.key}-${ci}`, commandText(cmd))">
                        <Icon :name="copied === `${step.key}-${ci}` ? 'mdi:check' : 'mdi:content-copy'" />
                      </button>
                    </div>
                    <p v-if="step.commands.some(hasPlaceholder)" class="fk-rb-note">
                      <Icon name="mdi:information-outline" class="fk-note-icon" />{{ t('frameKitView.steps.placeholders', 'Replace the highlighted values before you run it. Left as they are, the shell refuses the command.') }}
                    </p>
                  </div>
                </li>
              </ol>
            </section>

          </main>
        </div>

        <nav v-if="others.length" class="fk-others" :aria-label="t('frameKitView.others.label', 'Your other requests')">
          <h2 class="fk-h2 fk-h2--small">{{ t('frameKitView.others.title', 'Your other requests') }}</h2>
          <ul class="fk-others-list">
            <li v-for="o in others" :key="o.id">
              <button type="button" class="fk-other" :data-standing="standing(o) || 'requested'" @click="select(o.id)">
                <span class="fk-other-addr">{{ frameAddress(o) || o.id.slice(0, 8) }}</span>
                <span class="fk-other-meta">
                  <span class="fk-other-state">{{ stepLabel(standing(o) || 'requested') }}</span>
                  <span class="fk-other-when">{{ fmtDate(o.created_at) }}</span>
                </span>
              </button>
            </li>
          </ul>
        </nav>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * FrameKit: the applicant's own page for their frame (§HELLOFRAME, his word 2026-09-19: "the operator-portal is
 * outdated, make a glorious version for the frame export"). Behind FRAME_KIT_ENABLED (off by default): the router
 * guard and the sidebar hide it, and the registry answers 404 when the flag is off.
 *
 * The page leads with the frame's own address, shows where the request stands, hands over the kit (one object, one
 * seal drawn from its sha256) and lists the five steps to a federated frame with this request's values filled in.
 * Every decision lives in services/frameKit.ts (unit-tested) or in the registry (routers/frame_kit.py); this file renders.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { appLocale } from '@/services/appLocale'
import { frameKitService } from '@/services/api/frameKit'
import {
  commandText, formatBytes, frameAddress, hasPlaceholder, hostParts, pickRequest, sealTicks, shaGroups, shortSha, standing,
  standUpSteps, type FrameKitPage, type FrameKitRequest, type StandUpKey,
} from '@/services/frameKit'

const { t, tp } = useI18n()
const route = useRoute()
const router = useRouter()
const locale = appLocale()

const page = ref<FrameKitPage | null>(null)
const loading = ref(true)
const loadError = ref('')
const off = ref(false)
const selectedId = ref<string | null>(typeof route.query.request === 'string' ? route.query.request : null)

const current = computed<FrameKitRequest | null>(() => (page.value ? pickRequest(page.value.requests, selectedId.value) : null))
const others = computed(() => (page.value?.requests ?? []).filter(r => r.id !== current.value?.id))
const release = computed(() => page.value?.release ?? null)
const kit = computed(() => current.value?.kit ?? null)
const selfHosted = computed(() => current.value?.hosting === 'self')
const declined = computed(() => current.value?.status === 'rejected')
const ready = computed(() => kit.value?.state === 'ready')
const networkName = computed(() => page.value?.network.name || t('frameKitView.network.fallback', 'the network'))
const standUp = computed(() => (current.value && selfHosted.value && page.value
  ? standUpSteps(current.value, release.value, page.value.network) : []))
const ticks = computed(() => (release.value ? sealTicks(release.value.sha256) : []))
const address = computed(() => (current.value ? frameAddress(current.value) : ''))
// The headline is the hostname when the request has one, and then it breaks after its dots; otherwise it is the name,
// and the line above it names the organization instead of repeating it.
const addressIsHost = computed(() => !!(current.value?.hostname || current.value?.trust_domain))
const addressParts = computed(() => (addressIsHost.value ? hostParts(address.value) : [address.value]))
const contextName = computed(() => {
  const r = current.value
  const fallback = t('frameKitView.hero.context', 'Your frame')
  if (!r) return fallback
  return (addressIsHost.value ? r.display_name || r.organization : r.organization) || fallback
})
// The check only means something once there is a file to check.
const showVerify = computed(() => ready.value || (kit.value?.downloads_used ?? 0) > 0)
const downloadsLeft = computed(() => Math.max(0, (kit.value?.downloads_max ?? 0) - (kit.value?.downloads_used ?? 0)))
const viewState = computed(() => (loading.value ? 'loading' : off.value ? 'off' : loadError.value ? 'error'
  : !current.value ? 'empty' : selfHosted.value ? `kit-${kit.value?.state}` : `hosting-${current.value.hosting || 'unknown'}`))

const hostingLabel = computed(() => {
  if (current.value?.hosting === 'self') return t('frameKitView.hero.self', 'On your infrastructure')
  if (current.value?.hosting === 'theprotocol') return t('frameKitView.hero.hosted', 'Hosted by TheProtocol')
  return ''
})
const sealTicker = computed(() => (current.value?.ticker || 'KIT').slice(0, 6))
const sealCaption = computed(() => (release.value ? shortSha(release.value.sha256).slice(0, 8) : t('frameKitView.kit.sealEmpty', 'no kit yet')))
const sealLabel = computed(() => (release.value
  ? tp('frameKitView.kit.sealLabel', 'Kit seal drawn from sha256 {sha}', { sha: shortSha(release.value.sha256) })
  : t('frameKitView.kit.sealEmptyLabel', 'No kit is published yet')))

const progressOf = (key: string) => current.value?.progress.find(s => s.key === key)
const lede = computed(() => {
  const r = current.value
  if (!r) return ''
  if (r.status === 'rejected') return t('frameKitView.lede.declined', 'This request was not approved. You can ask again with a new request.')
  if (r.hosting === 'theprotocol') {
    return r.status === 'provisioned'
      ? t('frameKitView.lede.hostedLive', 'Your frame runs on our infrastructure.')
      : t('frameKitView.lede.hostedWaiting', 'We are reviewing your request. We build the frame once it is approved.')
  }
  if (r.hosting !== 'self') return t('frameKitView.lede.unknown', 'Your request is in. We will be in touch about where the frame runs.')
  const state = r.kit.state
  if (state === 'locked') return t('frameKitView.lede.locked', 'We are reviewing your request. The kit opens here when it is approved.')
  if (progressOf('federated')?.state === 'done') return tp('frameKitView.lede.federated', 'Your frame is federated with {network}.', { network: networkName.value })
  if (progressOf('invited')?.state === 'done') return tp('frameKitView.lede.invited', 'Your frame asked to join {network}. We approve the invitation here, and then your frame applies its licence.', { network: networkName.value })
  if (state === 'ready') {
    return progressOf('downloaded')?.state === 'done'
      ? t('frameKitView.lede.downloaded', 'You have the kit. Stand the frame up, then send its invitation with the last step.')
      : t('frameKitView.lede.ready', 'Approved. Your kit is ready, and the steps below are filled in for your frame.')
  }
  return r.kit.sentence || ''
})
const ledeTone = computed(() => (declined.value ? 'bad' : ready.value || progressOf('federated')?.state === 'done' ? 'good' : 'plain'))
const closedSentence = computed(() => kit.value?.sentence || '')

// Labels
const STEP_LABELS: Record<string, [string, string]> = {
  requested: ['frameKitView.progress.requested', 'Requested'],
  approved: ['frameKitView.progress.approved', 'Approved'],
  downloaded: ['frameKitView.progress.downloaded', 'Kit downloaded'],
  invited: ['frameKitView.progress.invited', 'Invitation sent'],
  federated: ['frameKitView.progress.federated', 'Federated'],
  reviewed: ['frameKitView.progress.reviewed', 'Reviewed'],
  provisioned: ['frameKitView.progress.provisioned', 'Running'],
  declined: ['frameKitView.progress.declined', 'Not approved'],
}
const stepLabel = (key: string) => (STEP_LABELS[key] ? t(STEP_LABELS[key][0], STEP_LABELS[key][1]) : key)

const RUNBOOK: Record<StandUpKey, { title: [string, string]; lead: [string, string] }> = {
  unpack: {
    title: ['frameKitView.steps.unpack.title', 'Unpack and build'],
    lead: ['frameKitView.steps.unpack.lead', 'Unpack the kit on your host and build its six images. The build takes a few minutes and needs no account anywhere.'],
  },
  dns: {
    title: ['frameKitView.steps.dns.title', 'Point your names at the host'],
    lead: ['frameKitView.steps.dns.lead', 'Two A records: your frame’s name, and a wildcard for the cloud operators it can run later.'],
  },
  doctor: {
    title: ['frameKitView.steps.doctor.title', 'Check the host'],
    lead: ['frameKitView.steps.doctor.lead', 'The doctor checks Docker, memory, disk, the five ports and your DNS name. It writes nothing, and each refusal says what to fix.'],
  },
  up: {
    title: ['frameKitView.steps.up.title', 'Start the frame'],
    lead: ['frameKitView.steps.up.lead', 'About five minutes. The admin password and the service accounts go to a secrets folder next to the stack, never to the screen.'],
  },
  federate: {
    title: ['frameKitView.steps.federate.title', 'Join the network'],
    lead: ['frameKitView.steps.federate.lead', 'frame-up prints this command when it finishes, with your stack directory filled in. Your frame imports this network’s trust root and sends its invitation. We approve it here, and your frame applies its licence. If it stops at the wait, run it again later; it picks up where it left off.'],
  },
}
const stepTitle = (k: StandUpKey) => t(RUNBOOK[k].title[0], RUNBOOK[k].title[1])
const stepLead = (k: StandUpKey) => t(RUNBOOK[k].lead[0], RUNBOOK[k].lead[1])

const NEEDS = ['docker', 'resources', 'ports', 'dns', 'mail'] as const
type Need = typeof NEEDS[number]
const NEED_LABELS: Record<Need, [string, string]> = {
  docker: ['frameKitView.needs.docker', 'Linux with Docker and the Compose plugin, version 2.24 or newer'],
  resources: ['frameKitView.needs.resources', '8 GiB of free memory and 20 GB of free disk'],
  ports: ['frameKitView.needs.ports', 'Ports 80 and 443 open for the console, and 8443 to 8445 for the machine lanes'],
  dns: ['frameKitView.needs.dns', 'Your hostname and its wildcard pointing at this host'],
  mail: ['frameKitView.needs.mail', 'A mail relay, so your frame can send verification and notice mail'],
}
const needLabel = (n: Need) => t(NEED_LABELS[n][0], NEED_LABELS[n][1])

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString(locale, { day: 'numeric', month: 'short', year: 'numeric' })
}

function detailOf(e: unknown, fallback: string): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof d === 'string' && d.trim() ? d : fallback
}

async function load() {
  loading.value = page.value === null
  loadError.value = ''
  try {
    page.value = await frameKitService.mine()
    off.value = false
  } catch (e) {
    const status = (e as { response?: { status?: number } })?.response?.status
    const friendly = t('frameKitView.error.lead', 'The registry did not answer. Your request is safe; try again in a moment.')
    if (status === 404) off.value = true
    // A 4xx carries a sentence the registry wrote for this person; a 5xx or no answer carries nothing they can use.
    else loadError.value = status && status < 500 ? detailOf(e, friendly) : friendly
  } finally {
    loading.value = false
  }
}

function select(id: string) {
  void router.replace({ query: { ...route.query, request: id } })
}
// A query-only change reuses this component (vue-router), so the door must listen as well as read at mount.
watch(() => route.query.request, v => { selectedId.value = typeof v === 'string' ? v : null })

// Downloads: a single-use link the browser's own download manager fetches (the kit is too large for a JS blob).
const downloading = ref(false)
const downloadNote = ref('')
const downloadError = ref('')
let refreshTimer: ReturnType<typeof setTimeout> | null = null
async function download() {
  if (!current.value || !ready.value || downloading.value) return
  downloading.value = true
  downloadError.value = ''
  downloadNote.value = ''
  try {
    const link = await frameKitService.link(current.value.id)
    window.location.assign(link.url)
    downloadNote.value = t('frameKitView.kit.started', 'Your download has started. When it finishes, check it against the sha256 below.')
    if (refreshTimer) clearTimeout(refreshTimer)
    refreshTimer = setTimeout(() => { void load() }, 2500)
  } catch (e) {
    downloadError.value = detailOf(e, t('frameKitView.kit.linkFailed', 'The download could not start. Try again in a moment.'))
  } finally {
    downloading.value = false
  }
}

// Copy, with a fallback for a context without the async clipboard.
const copied = ref('')
let copiedTimer: ReturnType<typeof setTimeout> | null = null
async function copy(key: string, text: string) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const area = document.createElement('textarea')
    area.value = text
    area.setAttribute('readonly', '')
    area.style.position = 'fixed'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    try { document.execCommand('copy') } catch { /* nothing more to try */ }
    document.body.removeChild(area)
  }
  copied.value = key
  if (copiedTimer) clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => { copied.value = '' }, 1600)
}

// The host checklist is a convenience for this browser only; storage that throws leaves the boxes unticked.
const checked = ref<Record<string, boolean>>({})
const needsKey = (id: string) => `frameKit.needs.${id}`
watch(current, r => {
  if (!r) { checked.value = {}; return }
  try {
    const saved = JSON.parse(localStorage.getItem(needsKey(r.id)) || '{}')
    checked.value = saved && typeof saved === 'object' ? saved : {}
  } catch {
    checked.value = {}
  }
}, { immediate: true })
function toggleNeed(n: Need) {
  if (!current.value) return
  checked.value = { ...checked.value, [n]: !checked.value[n] }
  try { localStorage.setItem(needsKey(current.value.id), JSON.stringify(checked.value)) } catch { /* not kept, still ticked */ }
}

onMounted(load)
onBeforeUnmount(() => {
  if (refreshTimer) clearTimeout(refreshTimer)
  if (copiedTimer) clearTimeout(copiedTimer)
})
</script>

<style scoped>
/* The house tokens (Design_Language.md): the accent follows the theme, the semantic colours do not. */
.fk {
  --fk-accent: var(--nc-primary, #00d2d2);
  --fk-accent-rgb: var(--nc-primary-rgb, 0, 210, 210);
  /* small text in the accent: the palette's bright step (the sovereign red is 3.9:1 on the card, its bright step 5.3:1) */
  --fk-accent-text: var(--nc-primary-bright, var(--fk-accent));
  --fk-text: var(--text, #e8eaed);
  --fk-text-2: var(--text-secondary, #b8c0cc);
  --fk-muted: #7d8594;
  --fk-line: rgba(var(--fk-accent-rgb), 0.16);
  --fk-well: rgba(4, 8, 14, 0.55);
  --fk-mono: 'IBM Plex Mono', 'Fira Code', ui-monospace, SFMono-Regular, Menlo, monospace;
  --fk-ok: #10b981;
  --fk-warn: #f59e0b;
  --fk-bad: #ef4444;
  --fk-on-accent: #041014;
  color: var(--fk-text);
  padding: 20px 0 80px;
}
:global(body.theme-sovereign) .fk { --fk-on-accent: #ffffff; }
.fk-wrap { max-width: 1180px; margin: 0 auto; padding-inline: clamp(16px, 3vw, 32px); box-sizing: border-box; }
.fk-quiet { margin: 48px 0; color: var(--fk-muted); font-size: 14px; }

/* Empty, off and error: an invitation to act, left-aligned like the rest of the page */
.fk-empty { max-width: 60ch; padding: 56px 0; }
.fk-empty-title { margin: 0; font-size: clamp(24px, 3.4vw, 32px); font-weight: 750; letter-spacing: -0.01em; line-height: 1.15; text-wrap: balance; }
.fk-empty-lead { margin: 14px 0 24px; font-size: 15.5px; line-height: 1.6; color: var(--fk-text-2); }

/* The hero: the frame's own address is the headline */
.fk-hero { padding: 12px 0 30px; border-bottom: 1px solid var(--fk-line); }
.fk-context { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin: 0 0 12px; font-size: 14px; color: var(--fk-text-2); }
.fk-hosting {
  display: inline-flex; align-items: center; padding: 2px 9px; border-radius: 999px; font-size: 12px;
  color: var(--fk-accent-text); background: rgba(var(--fk-accent-rgb), 0.1); border: 1px solid rgba(var(--fk-accent-rgb), 0.28);
}
.fk-host {
  margin: 0; font-family: var(--fk-mono); font-weight: 600; font-size: clamp(24px, 4.6vw, 46px);
  line-height: 1.08; letter-spacing: -0.025em; overflow-wrap: anywhere; color: var(--fk-text);
}
/* A hostname wraps after a dot, never inside a label; a phone lets a label longer than the screen break at its hyphens. */
.fk-host-part { white-space: nowrap; }
.fk-lede { margin: 16px 0 0; max-width: 64ch; font-size: 16.5px; line-height: 1.55; color: var(--fk-text-2); }
.fk-lede[data-tone='good'] { position: relative; padding-left: 22px; color: var(--fk-text); }
.fk-lede[data-tone='good']::before {
  content: ''; position: absolute; left: 3px; top: 0.58em; width: 8px; height: 8px; border-radius: 50%;
  background: var(--fk-ok); box-shadow: 0 0 0 4px rgba(16, 185, 129, 0.16);
}
.fk-lede-cta { margin-top: 18px; }
.fk-lede[data-tone='bad'] { color: #f3b4b4; }
.fk-facts { display: flex; flex-wrap: wrap; gap: 14px 40px; margin: 26px 0 0; }
.fk-fact dt { font-size: 12.5px; color: var(--fk-muted); }
.fk-fact dd { margin: 4px 0 0; font-family: var(--fk-mono); font-size: 14px; color: var(--fk-text); overflow-wrap: anywhere; }
.fk-fact-plain { font-family: inherit !important; }
.fk-fact-soft { margin-left: 8px; font-family: inherit; color: var(--fk-text-2); }

/* Two columns: the story on the left, the kit in view on the right */
.fk-grid { display: grid; grid-template-columns: minmax(0, 1fr) 356px; gap: 48px; align-items: start; margin-top: 36px; }
.fk-main { min-width: 0; grid-column: 1; grid-row: 1; }
/* Not sticky: the app sets html, body { overflow-x: hidden }, which makes the body a scroll container that never
   scrolls, so position: sticky resolves against it and never engages anywhere in the app (measured: the card at -866 px
   with the page scrolled 1300 px). The kit card sits at the top, where the page opens. */
.fk-aside { grid-column: 2; grid-row: 1; }
@media (max-width: 1080px) {
  .fk-grid { grid-template-columns: minmax(0, 1fr); gap: 32px; margin-top: 28px; }
  .fk-aside { grid-column: 1; grid-row: 1; }
  .fk-main { grid-row: 2; }
}

.fk-section { margin-bottom: 52px; }
.fk-section-head { margin-bottom: 20px; }
.fk-h2 { margin: 0 0 18px; font-size: 20px; font-weight: 700; letter-spacing: -0.005em; text-wrap: balance; }
.fk-section-head .fk-h2 { margin-bottom: 6px; }
.fk-h2--small { font-size: 16px; margin-bottom: 12px; }
.fk-section-lead { margin: 0; max-width: 66ch; font-size: 14.5px; line-height: 1.6; color: var(--fk-text-2); }
.fk-h3 { margin: 0; font-size: 16px; font-weight: 700; }

/* Progress: a rail of the request's real steps */
.fk-track { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(var(--steps, 5), minmax(0, 1fr)); }
.fk-track-step { position: relative; padding-top: 34px; padding-right: 8px; }
.fk-track-step::before {
  content: ''; position: absolute; top: 11px; left: 24px; right: 0; height: 2px; background: rgba(var(--fk-accent-rgb), 0.14);
}
.fk-track-step:last-child::before { display: none; }
.fk-track-step[data-state='done']::before { background: rgba(var(--fk-accent-rgb), 0.55); }
.fk-track-dot {
  position: absolute; top: 0; left: 0; width: 24px; height: 24px; border-radius: 50%; display: grid; place-items: center;
  box-sizing: border-box; border: 2px solid rgba(var(--fk-accent-rgb), 0.3); background: var(--nc-bg, #070b12); color: #041014; font-size: 14px;
}
.fk-track-step[data-state='done'] .fk-track-dot { background: var(--fk-accent); border-color: var(--fk-accent); color: var(--fk-on-accent); }
.fk-track-step[data-state='current'] .fk-track-dot { border-color: var(--fk-accent); box-shadow: 0 0 0 5px rgba(var(--fk-accent-rgb), 0.14); }
.fk-track-step[data-state='current'] .fk-track-dot::after { content: ''; width: 8px; height: 8px; border-radius: 50%; background: var(--fk-accent); }
.fk-track-step[data-state='declined'] .fk-track-dot { background: var(--fk-bad); border-color: var(--fk-bad); color: #fff; }
.fk-track-label { display: block; font-size: 14px; font-weight: 600; color: var(--fk-text); }
.fk-track-step[data-state='ahead'] .fk-track-label { color: var(--fk-muted); font-weight: 500; }
.fk-track-when { display: block; margin-top: 3px; font-size: 12.5px; color: var(--fk-muted); font-variant-numeric: tabular-nums; min-height: 1.2em; }
.fk-track-step[data-state='current'] .fk-track-when { color: var(--fk-accent-text); }
@media (max-width: 640px) {
  .fk-track { grid-template-columns: 1fr; gap: 0; }
  .fk-track-step { padding: 0 0 18px 40px; min-height: 42px; }
  .fk-track-step::before { top: 26px; bottom: 0; left: 11px; right: auto; width: 2px; height: auto; }
  .fk-track-when { display: inline; margin: 0 0 0 10px; }
  .fk-track-label { display: inline; }
}

/* The runbook: numbered because it is a sequence */
.fk-runbook { list-style: none; margin: 0; padding: 0; }
.fk-rb-step { display: grid; grid-template-columns: 44px minmax(0, 1fr); gap: 0 14px; padding-bottom: 30px; position: relative; }
.fk-rb-step:not(:last-child)::after {
  content: ''; position: absolute; left: 17px; top: 42px; bottom: 6px; width: 1px; background: var(--fk-line);
}
.fk-rb-num {
  width: 36px; height: 36px; border-radius: 50%; display: grid; place-items: center; font-family: var(--fk-mono);
  font-size: 15px; font-weight: 600; color: var(--fk-accent-text); border: 1px solid rgba(var(--fk-accent-rgb), 0.4);
  background: rgba(var(--fk-accent-rgb), 0.06);
}
.fk-rb-body { min-width: 0; padding-top: 6px; }
.fk-rb-lead { margin: 6px 0 14px; max-width: 66ch; font-size: 14.5px; line-height: 1.6; color: var(--fk-text-2); }
.fk-rb-note { display: flex; gap: 8px; align-items: flex-start; margin: 10px 0 0; font-size: 13px; line-height: 1.5; color: var(--fk-muted); }
.fk-note-icon { flex: 0 0 auto; margin-top: 2px; }

/* A command: a dark well, the text in its own scroller, the copy button in its own column (nothing covers a character) */
.fk-cmd {
  display: flex; align-items: flex-start; margin-top: 10px; border-radius: 8px; background: var(--fk-well);
  border: 1px solid rgba(255, 255, 255, 0.07);
}
.fk-pre {
  flex: 1 1 auto; min-width: 0; margin: 0; padding: 13px 8px 13px 16px; overflow-x: auto; background: transparent;
  font-family: var(--fk-mono); font-size: 13px; line-height: 1.7; color: #d7dde6; white-space: pre; tab-size: 4;
}
.fk-line { display: block; }
/* one command across lines: the continuation lines sit under the command they continue */
.fk-cmd:not(.fk-cmd--script) .fk-line + .fk-line { padding-left: 4ch; }
.fk-cont { color: var(--fk-muted); }
.fk-ph {
  color: #fbd38d; background: rgba(245, 158, 11, 0.12); border-radius: 4px; padding: 0 4px;
  box-shadow: inset 0 -1px 0 rgba(245, 158, 11, 0.45); font-family: var(--fk-mono);
}
.fk-copy {
  flex: 0 0 auto; margin: 7px 7px 7px 0; width: 34px; height: 34px; display: grid; place-items: center; border-radius: 7px;
  cursor: pointer; color: var(--fk-text-2); background: rgba(255, 255, 255, 0.04); border: 1px solid rgba(255, 255, 255, 0.08);
  transition: color 0.15s, background 0.15s, border-color 0.15s;
}
.fk-copy:hover { color: var(--fk-accent-text); border-color: rgba(var(--fk-accent-rgb), 0.4); background: rgba(var(--fk-accent-rgb), 0.08); }
.fk-copy:focus-visible, .fk-btn:focus-visible, .fk-sha:focus-visible, .fk-other:focus-visible {
  outline: none; box-shadow: 0 0 0 3px rgba(var(--fk-accent-rgb), 0.35);
}
/* the check command in the kit card wraps: one short command in a narrow card, copied whole by the button */
.fk-cmd--compact .fk-pre { padding-block: 9px; padding-left: 12px; font-size: 12px; white-space: pre-wrap; overflow-wrap: anywhere; }
.fk-cmd--compact .fk-copy { margin: 4px 4px 4px 0; width: 30px; height: 30px; }

.fk-dns { width: 100%; max-width: 560px; border-collapse: collapse; font-size: 13.5px; margin-top: 4px; }
.fk-dns th { text-align: left; font-weight: 500; font-size: 12.5px; color: var(--fk-muted); padding: 0 16px 8px 0; }
.fk-dns td { padding: 8px 16px 8px 0; border-top: 1px solid var(--fk-line); vertical-align: top; }
.fk-dns-name { font-family: var(--fk-mono); overflow-wrap: anywhere; }
@media (max-width: 640px) {
  /* a record reads as one unit on a phone: its type and name, and under them what it points to */
  .fk-dns thead { display: none; }
  .fk-dns tr { display: grid; grid-template-columns: 30px minmax(0, 1fr); padding: 9px 0; border-top: 1px solid var(--fk-line); }
  .fk-dns td { padding: 0; border: 0; }
  .fk-dns td:nth-child(3) { grid-column: 2; margin-top: 4px; }
}

/* Host needs */
.fk-needs { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; max-width: 640px; }
.fk-need {
  display: flex; align-items: flex-start; gap: 12px; padding: 11px 14px; border-radius: 8px; cursor: pointer;
  border: 1px solid var(--fk-line); background: rgba(var(--fk-accent-rgb), 0.025); transition: border-color 0.15s, background 0.15s;
}
.fk-need:hover { border-color: rgba(var(--fk-accent-rgb), 0.32); }
.fk-need[data-done='1'] { background: rgba(16, 185, 129, 0.06); border-color: rgba(16, 185, 129, 0.35); }
.fk-need-box { position: absolute; opacity: 0; width: 1px; height: 1px; }
.fk-need-mark {
  flex: 0 0 20px; height: 20px; margin-top: 1px; border-radius: 5px; display: grid; place-items: center; font-size: 14px;
  border: 1.5px solid rgba(var(--fk-accent-rgb), 0.45); color: #041014;
}
.fk-need[data-done='1'] .fk-need-mark { background: var(--fk-ok); border-color: var(--fk-ok); }
.fk-need-box:focus-visible + .fk-need-mark { box-shadow: 0 0 0 3px rgba(var(--fk-accent-rgb), 0.35); }
.fk-need-text { font-size: 14.5px; line-height: 1.45; color: var(--fk-text); }
.fk-need[data-done='1'] .fk-need-text { color: var(--fk-text-2); }

/* The kit: the one house card on the page, and its seal */
.fk-kit {
  padding: 24px 24px 26px; border-radius: 14px;
  background: linear-gradient(168deg, rgba(255, 255, 255, 0.03), rgba(255, 255, 255, 0) 60%), rgba(var(--fk-accent-rgb), 0.045);
  border: 1px solid rgba(var(--fk-accent-rgb), 0.22); backdrop-filter: blur(9px) saturate(1.05);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04), 0 18px 44px -26px rgba(0, 0, 0, 0.85);
}
.fk-seal { display: block; width: 196px; height: 196px; margin: -4px auto 12px; overflow: visible; }
.fk-seal-ring { fill: none; stroke: rgba(var(--fk-accent-rgb), 0.5); stroke-width: 1.2; }
.fk-seal-halo { fill: none; stroke: rgba(var(--fk-accent-rgb), 0.1); stroke-width: 1; stroke-dasharray: 2 5; }
.fk-seal--empty .fk-seal-ring { stroke-dasharray: 3 5; stroke: rgba(var(--fk-accent-rgb), 0.35); }
.fk-seal-ticks line { stroke: var(--fk-accent); stroke-width: 2.6; stroke-linecap: round; opacity: var(--o); }
.fk-seal--live .fk-seal-ticks line {
  stroke-dasharray: calc(var(--len) * 1px) 999px; stroke-dashoffset: calc(var(--len) * 1px);
  animation: fk-draw 640ms cubic-bezier(0.2, 0.7, 0.2, 1) forwards; animation-delay: calc(var(--i) * 11ms);
}
@keyframes fk-draw { to { stroke-dashoffset: 0; } }
@media (prefers-reduced-motion: reduce) {
  .fk-seal--live .fk-seal-ticks line { animation: none; stroke-dashoffset: 0; }
}
.fk-seal-ticker { font-family: var(--fk-mono); font-size: 25px; font-weight: 600; fill: var(--fk-text); letter-spacing: 0.02em; }
.fk-seal-caption { font-family: var(--fk-mono); font-size: 10.5px; fill: var(--fk-muted); letter-spacing: 0.08em; }
.fk-kit-title { margin: 0; text-align: center; font-size: 19px; font-weight: 700; text-wrap: balance; }
.fk-kit-meta { margin: 6px 0 18px; text-align: center; font-size: 13.5px; color: var(--fk-text-2); font-variant-numeric: tabular-nums; }
.fk-kit-window { display: flex; justify-content: center; gap: 4px 16px; flex-wrap: wrap; margin: 12px 0 0; font-size: 12.5px; color: var(--fk-muted); font-variant-numeric: tabular-nums; text-align: center; }
.fk-kit-closed { margin: 12px 0 0; font-size: 13.5px; line-height: 1.55; color: var(--fk-text-2); text-align: center; }
.fk-kit-note { margin: 12px 0 0; font-size: 13px; line-height: 1.5; color: #9ee6c4; }
.fk-kit-error { margin: 12px 0 0; font-size: 13px; line-height: 1.5; color: #f3b4b4; }
.fk-kit--hosted { text-align: center; }
.fk-hosted-icon { font-size: 36px; color: var(--fk-accent); margin: 6px auto 12px; display: block; }

.fk-verify { margin-top: 22px; padding-top: 18px; border-top: 1px solid var(--fk-line); }
.fk-verify-title { margin: 0; font-size: 14px; font-weight: 700; }
.fk-verify-lead { margin: 4px 0 8px; font-size: 13px; line-height: 1.5; color: var(--fk-text-2); }
.fk-sha {
  display: block; width: 100%; margin-top: 10px; padding: 10px 12px; border-radius: 8px; cursor: pointer; text-align: left;
  background: transparent; border: 1px dashed rgba(var(--fk-accent-rgb), 0.3); color: var(--fk-text-2);
  transition: border-color 0.15s, background 0.15s;
}
.fk-sha:hover { border-color: rgba(var(--fk-accent-rgb), 0.55); background: rgba(var(--fk-accent-rgb), 0.05); }
/* the hash in eights, four to a row: compared group by group against the terminal; the copied text stays one string */
.fk-sha-hex { display: grid; grid-template-columns: repeat(4, max-content); gap: 2px 10px; font-family: var(--fk-mono); font-size: 12px; line-height: 1.6; letter-spacing: 0.03em; color: var(--fk-text); }
.fk-sha-action { display: inline-flex; align-items: center; gap: 6px; margin-top: 6px; font-size: 12.5px; color: var(--fk-accent-text); }

/* Buttons */
.fk-btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 8px; padding: 11px 18px; border-radius: 9px;
  cursor: pointer; text-decoration: none; font-size: 14.5px; font-weight: 650; color: var(--fk-accent-text);
  background: rgba(var(--fk-accent-rgb), 0.1); border: 1px solid rgba(var(--fk-accent-rgb), 0.35);
  transition: filter 0.15s, background 0.15s, transform 0.08s;
}
.fk-btn:hover:not(:disabled) { background: rgba(var(--fk-accent-rgb), 0.18); }
.fk-btn:active:not(:disabled) { transform: translateY(1px); }
.fk-btn:disabled { cursor: default; opacity: 0.5; }
.fk-btn--primary { color: var(--fk-on-accent); background: var(--fk-accent); border-color: var(--fk-accent); box-shadow: 0 10px 26px -14px rgba(var(--fk-accent-rgb), 0.9); }
.fk-btn--primary:hover:not(:disabled) { background: var(--fk-accent); filter: brightness(1.08); }
.fk-btn--primary:disabled { color: var(--fk-text-2); background: rgba(255, 255, 255, 0.05); border-color: rgba(255, 255, 255, 0.1); box-shadow: none; opacity: 1; }
.fk-btn--wide { width: 100%; padding-block: 13px; font-size: 15px; }
.fk-btn-icon { font-size: 18px; }

/* Other requests */
.fk-others { margin-top: 12px; padding-top: 28px; border-top: 1px solid var(--fk-line); }
.fk-others-list { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 10px; }
.fk-other {
  display: inline-flex; flex-direction: column; align-items: flex-start; gap: 2px; padding: 10px 14px; border-radius: 9px; cursor: pointer;
  background: rgba(var(--fk-accent-rgb), 0.03); border: 1px solid var(--fk-line); color: var(--fk-text); text-align: left;
}
.fk-other:hover { border-color: rgba(var(--fk-accent-rgb), 0.35); }
.fk-other-addr { font-family: var(--fk-mono); font-size: 13.5px; }
.fk-other-meta { display: flex; flex-wrap: wrap; gap: 2px 12px; font-size: 12px; }
.fk-other-state { color: var(--fk-text-2); }
.fk-other[data-standing='declined'] .fk-other-state { color: #f3b4b4; }
.fk-other[data-standing='federated'] .fk-other-state, .fk-other[data-standing='provisioned'] .fk-other-state { color: #9ee6c4; }
.fk-other-when { color: var(--fk-muted); }

@media (max-width: 640px) {
  .fk-rb-step { display: block; position: relative; padding-bottom: 28px; }
  .fk-rb-step:not(:last-child)::after { display: none; }
  .fk-rb-num { position: absolute; left: 0; top: 2px; width: 28px; height: 28px; font-size: 13px; }
  .fk-rb-body { padding-top: 0; }
  .fk-rb-body > .fk-h3 { display: flex; align-items: center; min-height: 32px; padding-left: 40px; }
  /* a phone shows the whole command: each line wraps, and the wrapped part hangs under its own line */
  .fk-pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12.5px; padding-left: 12px; }
  .fk-line { padding-left: 2ch; text-indent: -2ch; }
  .fk-cmd:not(.fk-cmd--script) .fk-line + .fk-line { padding-left: 6ch; }
}
@media (max-width: 480px) {
  .fk { padding-top: 8px; }
  .fk-kit { padding: 20px 18px 22px; }
  .fk-seal { width: 172px; height: 172px; }
  .fk-host-part { white-space: normal; }
  .fk-sha-hex { grid-template-columns: repeat(4, max-content); gap: 2px 8px; font-size: 11.5px; }
}
</style>
