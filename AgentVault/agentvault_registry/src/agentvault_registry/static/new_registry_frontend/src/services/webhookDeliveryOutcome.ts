/**
 * services/webhookDeliveryOutcome.ts — §DOCSFIX D6-786 (2026-10-17).
 *
 * ONE rule for the outcome of a webhook delivery attempt, the registry's own (services/webhook_service.py,
 * delivery_outcome_clause, which the delivery lists filter by): a 2xx answer is a delivery, any other answer is a failed
 * attempt (a 3xx too: redirects are not followed, and the registry retries it like any other failure, D6-765), and no
 * answer is pending (in flight, or none came: a timeout or a connection failure). The three partition every delivery, so
 * the counts shown beside a list add up to the list. "Failed" read 4xx/5xx here, so a redirect was counted nowhere.
 */
export type DeliveryOutcome = 'success' | 'failed' | 'pending'

export function deliveryOutcome(status: number | null | undefined): DeliveryOutcome {
  if (status === null || status === undefined) return 'pending'
  return status >= 200 && status < 300 ? 'success' : 'failed'
}
