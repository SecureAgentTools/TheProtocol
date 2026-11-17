<template>
  <!-- V0657 (b), item 6: the list of organizations. This registry's listed ones first (its own public list), then the
       ones the federated index read from every other registry, each with its home. Only listed organizations are on
       either list: an organization is named in public only when it says so. -->
  <section class="odir" data-testid="org-directory">
    <h2 class="odir__title">{{ t('orgDirectory.title', 'Organizations') }}</h2>

    <h3 class="odir__sub">{{ tp('orgDirectory.here', 'On this registry{home}', { home: localHome?.name ? ` (${localHome.name})` : '' }) }}</h3>
    <p v-if="localState === 'loading'" class="odir__muted">{{ t('orgDirectory.loading', 'Reading the list…') }}</p>
    <p v-else-if="localState === 'failed'" class="odir__muted" data-testid="org-directory-local-failed">{{ t('orgDirectory.failed', 'The list could not be read just now.') }}</p>
    <p v-else-if="!local.length" class="odir__muted" data-testid="org-directory-local-empty">{{ t('orgDirectory.noneHere', 'No organization of this registry is listed. An organization lists itself in its settings.') }}</p>
    <ul v-else class="odir__grid">
      <li v-for="o in local" :key="'l:' + o.id" class="odir__card" data-testid="org-directory-local" :data-slug="o.slug"
          :class="{ 'odir__card--on': highlight && o.slug === highlight }">
        <OrgCardBody :org="o" :logo="safeLogo({ logo: o.logo || null, home: localHome }) || undefined" />
      </li>
    </ul>

    <h3 class="odir__sub">{{ t('orgDirectory.federation', 'Across the federation') }}</h3>
    <p v-if="fedState === 'off'" class="odir__muted" data-testid="org-directory-fed-off">{{ t('orgDirectory.noIndex', 'This registry reads no federated index, so only its own organizations are listed here.') }}</p>
    <p v-else-if="fedState === 'loading'" class="odir__muted">{{ t('orgDirectory.loading', 'Reading the list…') }}</p>
    <p v-else-if="fedState === 'unsupported'" class="odir__muted" data-testid="org-directory-fed-unsupported">{{ t('orgDirectory.indexOld', 'The federated index does not list organizations yet.') }}</p>
    <p v-else-if="fedState === 'failed'" class="odir__muted" data-testid="org-directory-fed-failed">{{ t('orgDirectory.indexFailed', 'The federated index could not be read just now.') }}</p>
    <p v-else-if="!federation.length" class="odir__muted" data-testid="org-directory-fed-empty">{{ t('orgDirectory.noneElsewhere', 'No other registry lists an organization yet.') }}</p>
    <ul v-else class="odir__grid">
      <li v-for="o in federation" :key="'f:' + o.source + ':' + o.id" class="odir__card" data-testid="org-directory-fed"
          :data-slug="o.slug || ''">
        <OrgCardBody :org="o" :logo="safeLogo({ logo: o.logo, home: o.home }) || undefined" :home-name="o.home?.name || o.source"
                     :page="o.page || undefined" />
      </li>
    </ul>
  </section>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, onMounted, ref, watch } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { organizationService, type ListedOrganization } from '@/services/api/organizationService'
import { directoryService, type DirectoryOrganization } from '@/services/api/directory'
import { safeLogo } from '@/services/orgMark'
import { agentsWork, agentsWorkIsNone } from '@/services/firmCounts'
import { safeExternalUrl } from '@/utils/safeUrl'

defineProps<{ highlight?: string | null }>()
const { t, tp } = useI18n()
const { loaded, directoryUrl } = useRegistryConfig()

const local = ref<ListedOrganization[]>([])
const localHome = ref<{ name?: string | null; origin?: string | null; console?: string | null } | null>(null)
const localState = ref<'loading' | 'ready' | 'failed'>('loading')
const allFed = ref<DirectoryOrganization[]>([])
const fedState = ref<'loading' | 'ready' | 'failed' | 'unsupported' | 'off'>('loading')

/** the federation's organizations, without this registry's own (they are listed above) */
const federation = computed(() => allFed.value.filter((o) => {
  const mine = localHome.value
  if (!mine) return true
  if (mine.origin && o.home?.origin && o.home.origin === mine.origin) return false
  return !(mine.name && (o.home?.name === mine.name || o.source === mine.name))
}))

function countsLine(o: { member_count?: number; agent_count?: number; settled_work?: number;
  memberCount?: number | null; agentCount?: number | null; settledWork?: number | null }): string {
  const m = o.member_count ?? o.memberCount
  const a = o.agent_count ?? o.agentCount
  const w = o.settled_work ?? o.settledWork
  const parts: string[] = []
  if (typeof m === 'number') parts.push(tp('orgDirectory.members', '{n} members', { n: m }))
  if (typeof a === 'number') parts.push(tp('orgDirectory.agents', '{n} agents', { n: a }))
  // V0658 (v), item 6: this is the work settled AS the firm; its agents' own work is a line of its own (memberWorkLine)
  if (typeof w === 'number' && w > 0) {
    parts.push(w === 1 ? t('orgDirectory.workOne', '1 job settled as the firm')
      : tp('orgDirectory.work', '{n} jobs settled as the firm', { n: w }))
  }
  return parts.join(' · ')
}

/** V0666: the settled work the organization's agents did and posted (this registry's list answers it as `member_work`, by
 *  the organization each agent belonged to at the award), never added into the firm's count; nothing when they have none
 *  or the answer does not say (a list row stays short: the Firms page says why a zero is a zero). */
function memberWorkLine(o: { member_work?: { jobs?: number; commissioned?: number } | null }): string {
  const w = agentsWork(o.member_work)
  if (!w || agentsWorkIsNone(w)) return ''
  return tp('orgDirectory.agentsWork', 'By its agents: {d} jobs delivered, {c} commissioned', { d: w.jobs, c: w.commissioned })
}

const OrgCardBody = defineComponent({
  props: { org: { type: Object, required: true }, logo: { type: String, default: null },
    homeName: { type: String, default: null }, page: { type: String, default: null } },
  setup(p) {
    const broken = ref(false)
    return () => {
      const o: any = p.org
      const site = typeof o.website === 'string' && /^https?:\/\//i.test(o.website) ? safeExternalUrl(o.website) : undefined
      const href = typeof p.page === 'string' && /^https?:\/\//i.test(p.page) ? safeExternalUrl(p.page) : undefined
      return h('div', { class: 'odir__body' }, [
        h('div', { class: 'odir__logo' }, p.logo && !broken.value
          ? [h('img', { src: p.logo, alt: '', loading: 'lazy', referrerpolicy: 'no-referrer', onError: () => { broken.value = true } })]
          : [h('span', { 'aria-hidden': 'true' }, '◈')]),
        h('div', { class: 'odir__text' }, [
          href ? h('a', { class: 'odir__name', href, target: '_blank', rel: 'noopener noreferrer' }, o.name)
            : h('span', { class: 'odir__name' }, o.name),
          o.description ? h('span', { class: 'odir__desc' }, o.description) : null,
          h('span', { class: 'odir__meta' }, [countsLine(o), p.homeName ? ` · ${p.homeName}` : ''].join('')),
          memberWorkLine(o) ? h('span', { class: 'odir__members', 'data-testid': 'org-directory-member-work',
            title: t('orgDirectory.memberTip', 'Guild work its agents did or posted as themselves, not as the firm. Counted by the organization each belonged to when the order was awarded, shown apart from the firm\'s own count, never added to it.') },
          memberWorkLine(o)) : null,
          site ? h('a', { class: 'odir__site', href: site, target: '_blank', rel: 'noopener noreferrer nofollow' }, site) : null,
        ]),
      ])
    }
  },
})

async function loadLocal() {
  localState.value = 'loading'
  try {
    const out = await organizationService.listListedOrganizations()
    local.value = out.organizations || []
    localHome.value = out.home || null
    localState.value = 'ready'
  } catch {
    localState.value = 'failed'
  }
}

async function loadFederation() {
  if (!loaded.value) return
  if (!directoryUrl.value) { fedState.value = 'off'; return }
  fedState.value = 'loading'
  try {
    const out = await directoryService.organizations(directoryUrl.value, 200)
    allFed.value = out.edges
    fedState.value = out.supported ? 'ready' : 'unsupported'
  } catch {
    fedState.value = 'failed'
  }
}

watch(loaded, (v) => { if (v) loadFederation() })
onMounted(() => { loadLocal(); loadFederation() })
defineExpose({ loadLocal, loadFederation })
</script>

<style scoped>
.odir { margin: 0 0 28px; }
.odir__title { font-size: 1.1rem; font-weight: 400; letter-spacing: .04em; margin: 0 0 6px; }
.odir__sub { font-size: .8rem; text-transform: uppercase; letter-spacing: .06em; opacity: .65; margin: 16px 0 8px; }
.odir__muted { font-size: .82rem; opacity: .65; margin: 0; }
.odir__grid { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); }
.odir__card { border: 1px solid var(--border-color, rgba(128,128,128,.25)); border-radius: 10px; padding: 12px; }
.odir__card--on { border-color: var(--nc-primary, #4fd8c4); }
:deep(.odir__body) { display: flex; gap: 10px; min-width: 0; }
:deep(.odir__logo) { flex: 0 0 40px; width: 40px; height: 40px; border-radius: 10px; overflow: hidden; display: flex;
  align-items: center; justify-content: center; background: rgba(128,128,128,.1); }
:deep(.odir__logo img) { width: 100%; height: 100%; object-fit: cover; }
:deep(.odir__text) { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
:deep(.odir__name) { font-weight: 600; color: inherit; overflow-wrap: anywhere; }
:deep(.odir__desc) { font-size: .78rem; opacity: .75; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
:deep(.odir__meta) { font-size: .72rem; opacity: .6; }
/* V0658 (v): a declared colour (an opacity over the inherited one is the class the proof's contrast gate fails) */
:deep(.odir__members) { font-size: .72rem; color: rgba(148, 163, 184, 0.85); }
:deep(.odir__site) { font-size: .72rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
