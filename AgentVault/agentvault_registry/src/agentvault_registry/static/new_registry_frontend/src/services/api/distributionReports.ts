// V0667 D7 (order gwo_0f317438b7dfc6dfacd3e9b7): the signed release report of an organization's line and the signed record of one of its changes (routers/distribution_reports.py). Members and platform admins read them;
// the document is the registry's envelope, signed with its card key, and is checked OFFLINE against /.well-known/registry-jwks.json (theprotocol.registry.verify_distribution_envelope in the SDK).
import { apiClient } from './client'

const q = encodeURIComponent
export type SignedDocument = Record<string, any>

export async function getReport(slug: string): Promise<SignedDocument> {
  const { data } = await apiClient.get(`/code-distributions/${q(slug)}/report`, { expectedStatuses: [403, 404] })
  return data
}
export async function getRecord(slug: string, changeId: string): Promise<SignedDocument> {
  const { data } = await apiClient.get(`/code-distributions/${q(slug)}/records/${q(changeId)}`, { expectedStatuses: [403, 404] })
  return data
}
