// V0664 C3 (order gwo_4110e12c11a69a93de878829): the two reads My proxies makes, as the owner (a developer token: the
// /developers/ and /teg/transactions/history/ paths are developer-tier in services/api/tier.ts).
import { apiClient } from './client'
import { normalizeLedger, normalizeProxies, type LedgerRow, type ProxyRow } from '@/services/proxy/mine'

/** Every agent of the signed-in developer that reports a proxy status, newest first (C2's list route, at most 200). */
export async function myProxies(): Promise<ProxyRow[]> {
  // a registry without the route answers 404: the page says so itself, so no global toast says it again
  const { data } = await apiClient.get('/developers/me/proxy-status', { expectedStatuses: [404] })
  return normalizeProxies(data)
}

/** One agent's recent ledger rows (its owner's read). */
export async function agentLedger(did: string, limit = 10): Promise<LedgerRow[]> {
  // a refused or missing ledger is said beside its proxy, so no global toast says it again
  const { data } = await apiClient.get(`/teg/transactions/history/${encodeURIComponent(did)}`, { params: { limit }, expectedStatuses: [403, 404] })
  return normalizeLedger(data)
}
