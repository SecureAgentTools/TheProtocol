/**
 * §BATCH8 item 9 (2026-09-06) — POST a list in chunks with BOUNDED concurrency, and stop at the first 401.
 *
 * `Promise.all` over 83 chunks fired 83 requests in one tick; with a dead session every one of them was a 401
 * and CrowdSec read the burst as an attack. A bounded window keeps a bad token to at most `concurrency` refusals,
 * and `stopOn401` ends the run the moment the session is known dead (the interceptor has already tried its one
 * refresh by then). Pure over an injected `post`, so the shape is unit-testable without axios.
 */
export interface BatchedPostOptions {
  chunkSize?: number
  concurrency?: number
  stopOn401?: boolean
}

export interface BatchedPostResult<T> {
  results: T[]
  requests: number
  stoppedOn401: boolean
}

function statusOf(err: unknown): number | undefined {
  const e = err as { response?: { status?: number }; status?: number } | undefined
  return e?.response?.status ?? e?.status
}

export async function batchedPost<I, T>(
  items: I[],
  post: (chunk: I[]) => Promise<T>,
  opts: BatchedPostOptions = {},
): Promise<BatchedPostResult<T>> {
  const chunkSize = Math.max(1, opts.chunkSize ?? 50)
  const concurrency = Math.max(1, opts.concurrency ?? 4)
  const stopOn401 = opts.stopOn401 ?? true
  const chunks: I[][] = []
  for (let i = 0; i < items.length; i += chunkSize) chunks.push(items.slice(i, i + chunkSize))
  const results: T[] = []
  let requests = 0
  let stoppedOn401 = false
  let next = 0
  const worker = async () => {
    while (next < chunks.length && !stoppedOn401) {
      const chunk = chunks[next++]
      requests++
      try {
        results.push(await post(chunk))
      } catch (err) {
        if (stopOn401 && statusOf(err) === 401) {
          stoppedOn401 = true
          return
        }
        throw err
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, chunks.length) }, () => worker()))
  return { results, requests, stoppedOn401 }
}
