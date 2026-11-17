// V0662 console polish, item 7 (order gwo_0aa7b875cbf65b6347f5f775): the track record's probe line in words.
//
// The health checker probes whatever URL a card names, placeholders included (a spawned child's
// sub-<uuid>.agents.local), so its raw "unreachable" read as a service that is down for agents that never declared
// one. The registry's liveness block now says whether the card declares a live service (service_declared); this
// words the three states apart, the checker's outcome on the hover. A registry that does not say keeps the old
// neutral line.

type T = (key: string, fallback: string) => string

export interface Liveness {
  probe: string | null
  last_seen: string | null
  live_24h: boolean
  service_declared?: boolean
}

export interface ServiceLine {
  kind: 'none' | 'up' | 'down' | 'unknown' | 'probe'
  text: string
  title: string
}

export function serviceLine(lv: Liveness | null | undefined, t: T): ServiceLine | null {
  if (!lv) return null
  const outcome = lv.probe ? `${t('trackRecord.probe', 'endpoint probe')}: ${lv.probe}` : ''
  if (lv.service_declared === false) {
    return { kind: 'none', text: t('trackRecord.service.none', 'no live service declared'),
      title: outcome || t('trackRecord.service.noneTitle', 'The agent card names no reachable service address.') }
  }
  if (lv.service_declared === true) {
    if (lv.probe === 'healthy') return { kind: 'up', text: t('trackRecord.service.up', 'service answering'), title: outcome }
    if (lv.probe) return { kind: 'down', text: t('trackRecord.service.down', 'service not answering'), title: outcome }
    return { kind: 'unknown', text: t('trackRecord.service.unprobed', 'service not probed yet'), title: '' }
  }
  return lv.probe ? { kind: 'probe', text: outcome, title: '' } : null
}
