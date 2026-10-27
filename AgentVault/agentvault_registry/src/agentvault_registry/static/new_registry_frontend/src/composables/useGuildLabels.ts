/**
 * composables/useGuildLabels.ts — §POCKETI18N (2026-08-23).
 *
 * ONE place that turns `services/guildActions` output into words a human reads.
 * That module is PURE and unit-tested in a node env, so it may never import
 * i18n; it emits English plus a stable `noteKey`, and this composable resolves
 * the key with the English as the fallback. Both consumers of the gate that
 * render on a phone (PocketEarn's order sheet and the bridge WORK view) use
 * this, so the two surfaces cannot drift apart — the same rule that made
 * guildActions one brain in the first place.
 */
import { useI18n } from '@/composables/useI18n'
import type { GuildActionOffer } from '@/services/guildActions'

/** What actionsFor() returns — structural, so it needs no import cycle. */
export interface GuildGateLike {
  actions: GuildActionOffer[]
  note: string
  noteKey?: string
  noteParams?: Record<string, string>
}

export function useGuildLabels() {
  const { t, tp } = useI18n()

  /* The action set is CLOSED (award/submit/verify/cancel/bid) and carries no
     key of its own: GuildActionOffer is asserted with a deep toEqual in the
     guildActions suite, so an extra field there would break a green test. The
     English label stays the fallback. */
  const actionLabel = (a: GuildActionOffer): string => {
    switch (a.key) {
      case 'award': return t('pocket.guild.action.award', 'Award a bid')
      case 'submit': return t('pocket.guild.action.submit', 'Submit work')
      case 'verify': return t('pocket.guild.action.verify', 'Verify delivery')
      case 'cancel': return t('pocket.guild.action.cancel', 'Cancel order')
      case 'bid': return t('pocket.guild.action.bid', 'Place a bid')
      default: return a.label
    }
  }

  /* An unkeyed note renders its English verbatim rather than a key — a gate
     that explains nothing is worse than one that explains in the wrong
     language. */
  const noteText = (g: GuildGateLike | null | undefined): string => {
    if (!g || !g.note) return ''
    if (!g.noteKey) return g.note
    const key = 'pocket.guild.note.' + g.noteKey
    return g.noteParams ? tp(key, g.note, g.noteParams) : t(key, g.note)
  }

  /* Role words render on both surfaces as a chip. */
  const roleLabel = (r: string): string =>
    r === 'poster' ? t('pocket.guild.role.poster', 'poster')
      : r === 'worker' ? t('pocket.guild.role.worker', 'worker')
        : t('pocket.guild.role.observer', 'observer')

  /* Guild order status, as the API spells it. An unknown status renders raw:
     inventing a friendly word for a state we do not know would be a lie. */
  const STATUS: Record<string, [string, string]> = {
    open: ['pocket.guild.status.open', 'open'],
    awarded: ['pocket.guild.status.awarded', 'awarded'],
    in_progress: ['pocket.guild.status.inProgress', 'in progress'],
    submitted: ['pocket.guild.status.submitted', 'submitted'],
    delivered: ['pocket.guild.status.delivered', 'delivered'],
    settled: ['pocket.guild.status.settled', 'settled'],
    cancelled: ['pocket.guild.status.cancelled', 'cancelled'],
    canceled: ['pocket.guild.status.cancelled', 'cancelled'],
    disputed: ['pocket.guild.status.disputed', 'disputed'],
  }
  const statusLabel = (s?: string): string => {
    const v = String(s || '').toLowerCase()
    const e = STATUS[v]
    return e ? t(e[0], e[1]) : v
  }

  return { actionLabel, noteText, roleLabel, statusLabel }
}
