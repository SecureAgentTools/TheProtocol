<!-- MEMBERSHIP PANEL (§MEMBERSHIP, 2026-10-02) — "am I a member of this registry, with which weight, and if not, the
     one thing to do next". Shown where the registry runs governance in member mode; the parent decides that. The words
     are membership words only: members, bonds, vote weight. Nothing here is a reward, a yield or a share. -->
<template>
  <section class="mbp" :class="{ 'mbp--compact': compact }" data-testid="membership-panel" :data-state="state">
    <header class="mbp-head">
      <span class="mbp-title"><Icon name="mdi:account-group" /> {{ t('membership.title', 'Membership') }}</span>
      <span
        v-if="me"
        class="mbp-badge"
        :class="me.is_member ? 'mbp-badge--yes' : 'mbp-badge--no'"
        data-testid="membership-status"
        :data-member="me.is_member ? '1' : '0'"
      >
        <Icon :name="me.is_member ? 'mdi:account-check' : 'mdi:account-clock'" />
        {{ me.is_member
          ? tp('membership.memberSince', 'Member since {date}', { date: fmtDate(me.member_since) })
          : t('membership.notMember', 'Not a member yet') }}
      </span>
    </header>

    <p v-if="state === 'idle' || state === 'loading'" class="mbp-muted" aria-busy="true">…</p>
    <p v-else-if="state === 'signed-out'" class="mbp-muted">{{ t('membership.signInToSee', 'Sign in to see your membership.') }}</p>
    <p v-else-if="state === 'failed'" class="mbp-muted" role="status">{{ t('membership.loadFailed', 'Membership could not be read right now.') }}</p>

    <template v-else-if="me">
      <div v-if="me.is_member" class="mbp-weight" data-testid="membership-weight">
        <div class="mbp-weight__row">
          <span class="mbp-weight__value">{{ weightLabel(me.weight, locale) }}</span>
          <span class="mbp-weight__label">{{ t('membership.weight', 'Vote weight') }}</span>
        </div>
        <div class="mbp-bar" role="progressbar" :aria-valuenow="progressPct" aria-valuemin="0" aria-valuemax="100"
             :aria-label="t('membership.weight', 'Vote weight')">
          <div class="mbp-bar__fill" :style="{ width: progressPct + '%' }"></div>
        </div>
        <div class="mbp-muted">
          {{ tp('membership.tenure', '{days} days as a member', { days: me.tenure_days }) }} ·
          {{ daysToFull > 0 ? tp('membership.fullWeightIn', 'Full weight in {days} days', { days: daysToFull }) : t('membership.fullWeight', 'Full weight') }}
        </div>
      </div>

      <p v-else-if="nextStepText" class="mbp-next" data-testid="membership-next" :data-step="me.next_step">
        <Icon name="mdi:information-outline" />
        <span>
          {{ nextStepText }}
          <RouterLink v-if="me.next_step === 'cancel_deletion'" :to="{ path: '/settings', query: { tab: 'security' } }"
                      class="mbp-next__link" data-testid="membership-cancel-deletion">{{ t('membership.next.cancelDeletionLink', 'Cancel the deletion') }}</RouterLink>
        </span>
      </p>

      <ul v-if="me.agents.length && !compact" class="mbp-agents" data-testid="membership-bonds">
        <li class="mbp-agents__title">{{ t('membership.agentsTitle', 'Your bonds') }}</li>
        <li v-for="a in me.agents" :key="a.did + (a.locked_at || '')" class="mbp-agent" :data-qualifies="a.qualifies ? '1' : '0'">
          <RouterLink :to="{ name: 'agent-details', params: { agentId: a.did } }" class="mbp-agent__name"
                      :title="t('membership.openAgent', 'Open agent')">{{ a.name || a.did }}</RouterLink>
          <span class="mbp-agent__bond">{{ bondLabel(a.bond_status) }} · {{ fundedLabel(a.funded_by) }}</span>
          <span class="mbp-agent__verdict" :class="a.qualifies ? 'is-yes' : 'is-no'">{{ verdict(a) }}</span>
        </li>
      </ul>
      <!-- the server lists at most 20 bonds (those that count first, then those about to count); say it is a slice -->
      <p v-if="!compact && me.agents_total > me.agents.length" class="mbp-muted" data-testid="membership-bonds-slice">
        {{ tp('membership.agentsSlice', 'Showing {shown} of {total} bonds (bonds that count: {qualifying}); those that count come first, then those about to count.',
              { shown: fmtCount(me.agents.length), total: fmtCount(me.agents_total), qualifying: fmtCount(me.agents_qualifying) }) }}
      </p>

      <p v-if="!compact" class="mbp-hint">{{ tp('membership.weightHint', 'One vote per member. The weight grows with membership, from 1.00 to 2.00 after {days} days.', { days: me.tenure_full_days }) }}</p>
      <p v-if="presenceText" class="mbp-hint" data-testid="membership-presence">{{ presenceText }}</p>
    </template>

    <footer v-if="stats && !compact" class="mbp-foot" data-testid="membership-registry">
      <!-- §COCKPITDESK (2026-10-15): the camera read "1 members" -->
      {{ stats.members === 1
          ? tp('membership.registryLineOne', '1 member · {joined} joined and {left} left in the last 30 days',
               { joined: stats.joined_30d, left: stats.left_30d })
          : tp('membership.registryLine', '{members} members · {joined} joined and {left} left in the last 30 days',
               { members: stats.members, joined: stats.joined_30d, left: stats.left_30d }) }}
      · {{ tp('membership.rulesLine', 'A bond counts after {days} days', { days: stats.min_bond_age_days }) }}<template v-if="stats.requires_matured_bond">, {{ t('membership.rulesMatured', 'matured bonds only') }}</template>
      · <RouterLink :to="{ name: 'registries' }" class="mbp-board-link" data-testid="membership-board-link">{{ t('membership.compare', 'Compare registries') }}</RouterLink>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { useMembership } from '@/composables/useMembership'
import { appLocale } from '@/services/appLocale'
import { fmtCount } from '@/services/cockpit/num'
import { tenureProgress, weightLabel, type MembershipAgent, type MyMembership } from '@/services/membership/membership'

withDefaults(defineProps<{ compact?: boolean }>(), { compact: false })

const { t, tp } = useI18n()
const { me, stats, state, load } = useMembership()
const locale = computed(() => appLocale())

onMounted(() => { void load() })

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  try { return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium' }).format(d) } catch { return iso.slice(0, 10) }
}

const progressPct = computed(() => Math.round(tenureProgress(me.value?.tenure_days, me.value?.tenure_full_days) * 100))
const daysToFull = computed(() => Math.max(0, (me.value?.tenure_full_days ?? 0) - (me.value?.tenure_days ?? 0)))

const NEXT_FALLBACK: Record<MyMembership['next_step'], string> = {
  none: '',
  post_bond: 'Post the reputation bond for one of your agents, paid by the agent or from your wallet. It makes you a member {days} days later.',
  wait_until: 'Your bond counts from {date}. Nothing else to do.',
  use_own_funds: 'A bond the treasury paid for does not make a member. Post one paid by the agent or from your wallet.',
  wait_for_maturity: "This registry counts only matured bonds. The agent's bond panel shows what maturity still needs.",
  resolve_agent: 'The agent holding your bond is suspended. A bond on an active agent is needed.',
  verify_email: 'Verify your email address first. Only verified developers are members.',
  contact_support: 'Your account is suspended. Membership resumes when support lifts the suspension.',
  cancel_deletion: 'Your account is scheduled for deletion, and while it is, you are not a member. Cancel the deletion and you are a member again, from your original start date.',
}

const nextStepText = computed(() => {
  const m = me.value
  if (!m || m.next_step === 'none') return ''
  // a code this console does not know yet (a newer registry): the server's own sentence, never another step's advice
  if (!(m.next_step in NEXT_FALLBACK)) return m.next_step_text || ''
  const step = m.next_step
  return tp(`membership.next.${step}`, NEXT_FALLBACK[step], { days: m.min_bond_age_days, date: fmtDate(m.next_step_at) })
})

const presenceText = computed(() => {
  const p = me.value?.presence_mode
  if (p === 'conditional') return t('membership.presence.conditional', 'Binding votes are confirmed on your phone or with a code.')
  if (p === 'required') return t('membership.presence.required', 'Binding votes need a confirmed phone or an authenticator app.')
  return ''
})

const BOND_FALLBACK: Record<string, string> = { locked: 'Bonded', matured: 'Bond matured', released: 'Bond released', forfeited: 'Bond forfeited' }
function bondLabel(status: string | null): string {
  const s = status || ''
  return s in BOND_FALLBACK ? t(`agentDetails.bond.status.${s}`, BOND_FALLBACK[s]) : s
}
const FUNDED_FALLBACK: Record<string, string> = { self: 'paid by the agent', wallet: 'paid from your wallet', treasury: 'paid by the treasury' }
function fundedLabel(by: string | null): string {
  const b = by || ''
  return b in FUNDED_FALLBACK ? t(`membership.fundedBy.${b}`, FUNDED_FALLBACK[b]) : b
}
const REASON_FALLBACK: Record<string, string> = {
  bond: 'no bond', bond_age: 'bond too recent', bond_matured: 'bond not matured', bond_funded_by_treasury: 'paid by the treasury',
  agent_suspended: 'agent suspended', developer_unverified: 'email not verified', developer_suspended: 'account suspended',
}
function verdict(a: MembershipAgent): string {
  if (a.qualifies) return t('membership.qualifies', 'counts')
  // a dated "counts from" already says what "bond too recent" says; the other reasons stay
  const when = a.qualifies_at ? tp('membership.qualifiesOn', 'counts from {date}', { date: fmtDate(a.qualifies_at) }) : ''
  const reasons = (a.reasons || [])
    .filter(r => r in REASON_FALLBACK && !(when && r === 'bond_age'))
    .map(r => t(`membership.reason.${r}`, REASON_FALLBACK[r]))
  return [when, ...reasons].filter(Boolean).join(' · ')
}
</script>

<style scoped>
.mbp { background: rgba(255,255,255,0.02); border: 1px solid rgba(var(--nc-primary-rgb, 0,212,255), 0.14); border-radius: 10px; padding: 0.9rem 1rem; display: flex; flex-direction: column; gap: 0.55rem; }
.mbp--compact { padding: 0.7rem 0.8rem; gap: 0.4rem; }
.mbp-head { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; flex-wrap: wrap; }
.mbp-title { display: inline-flex; align-items: center; gap: 0.35rem; font-weight: 700; font-size: 0.85rem; letter-spacing: 0.02em; }
.mbp-title :deep(svg) { width: 1rem; height: 1rem; }
.mbp-badge { display: inline-flex; align-items: center; gap: 0.3rem; font-size: 0.72rem; font-weight: 700; padding: 0.2rem 0.55rem; border-radius: 999px; border: 1px solid; }
.mbp-badge :deep(svg) { width: 0.85rem; height: 0.85rem; }
.mbp-badge--yes { color: rgb(74,222,128); border-color: rgba(74,222,128,0.45); background: rgba(74,222,128,0.08); }
.mbp-badge--no { color: rgb(251,191,36); border-color: rgba(251,191,36,0.45); background: rgba(251,191,36,0.08); }
.mbp-weight__row { display: flex; align-items: baseline; gap: 0.5rem; }
.mbp-weight__value { font-size: 1.6rem; font-weight: 800; font-variant-numeric: tabular-nums; color: var(--nc-primary, #00d4ff); }
.mbp-weight__label { font-size: 0.75rem; opacity: 0.8; }
.mbp-bar { height: 6px; border-radius: 999px; background: rgba(255,255,255,0.08); overflow: hidden; margin: 0.35rem 0; }
.mbp-bar__fill { height: 100%; background: var(--nc-primary, #00d4ff); }
.mbp-next { display: flex; gap: 0.4rem; align-items: flex-start; margin: 0; font-size: 0.82rem; line-height: 1.45; }
.mbp-next__link { margin-left: 0.3rem; color: inherit; text-decoration: underline; text-underline-offset: 2px; white-space: nowrap; }
.mbp-next :deep(svg) { flex: 0 0 auto; width: 1rem; height: 1rem; margin-top: 0.1rem; color: rgb(251,191,36); }
.mbp-agents { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.3rem; }
.mbp-agents__title { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.06em; opacity: 0.7; }
.mbp-agent { display: flex; flex-wrap: wrap; gap: 0.25rem 0.6rem; align-items: baseline; font-size: 0.78rem; }
.mbp-agent__name { font-weight: 700; color: inherit; text-decoration: underline; text-underline-offset: 2px; }
.mbp-agent__bond { opacity: 0.8; }
.mbp-agent__verdict.is-yes { color: rgb(74,222,128); }
.mbp-agent__verdict.is-no { color: rgb(251,191,36); }
.mbp-hint, .mbp-muted { margin: 0; font-size: 0.74rem; opacity: 0.8; line-height: 1.45; }
.mbp-foot { font-size: 0.72rem; opacity: 0.8; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 0.5rem; }
.mbp-board-link { color: inherit; text-decoration: underline; text-underline-offset: 2px; }
</style>
