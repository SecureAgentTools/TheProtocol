// V0664 (order gwo_874694de65551c5c1488641c): the countdown and the retry behind a sender's own line while the cross-frame relay limit
// holds it back (the states and their numbers: services/chat/relayHold.ts). One timer, one second at a time; a line is retried with the
// SAME payload (its client_ref included), so the host takes it once however many tries it took.
import { ref } from 'vue'
import { dueRetry, failedLine, held, newLine, sentLine, settle as settleLines, tick, type PendingLine } from '@/services/chat/relayHold'

type SendPayload = { kind: 'text' | 'card'; body?: string; card?: any; client_ref: string; reply_to?: string }

export function useRelayHold(opts: { send: (payload: SendPayload) => Promise<any> }) {
  const lines = ref<PendingLine[]>([])
  const payloads = new Map<string, SendPayload>()
  const busy = new Set<string>()
  let timer: ReturnType<typeof setTimeout> | null = null

  const find = (ref_: string) => lines.value.find((l) => l.clientRef === ref_)
  function put(l: PendingLine) {
    const i = lines.value.findIndex((x) => x.clientRef === l.clientRef)
    if (i < 0) { lines.value = [...lines.value, l]; return }
    const next = [...lines.value]
    next[i] = l
    lines.value = next
  }
  function schedule() {
    if (timer || !lines.value.some((l) => l.state === 'waiting')) return
    timer = setTimeout(onTick, 1000)
  }
  async function attempt(ref_: string) {
    const cur = find(ref_)
    const payload = payloads.get(ref_)
    if (!cur || !payload || busy.has(ref_)) return
    busy.add(ref_)
    try {
      await opts.send(payload)
      put(sentLine(find(ref_) || cur))
    } catch (e: any) {
      const l = find(ref_) || cur
      // a limit, or a send that did not reach anyone (no status): try again later; any other refusal is the host's answer
      put(!e?.status || e.status === 429 ? held(l, e) : failedLine(l, e))
    } finally { busy.delete(ref_) }
  }
  async function onTick() {
    timer = null
    lines.value = lines.value.map(tick)
    for (const l of [...lines.value]) if (dueRetry(l)) await attempt(l.clientRef)
    schedule()
  }

  /** The limit held a send the sender just made (its first 429): the line waits, and goes again under the same client_ref. */
  function take(payload: SendPayload, err: { retryAfterS?: number; detail?: string } | null | undefined) {
    if (find(payload.client_ref)) return
    payloads.set(payload.client_ref, payload)
    put(held(newLine({ clientRef: payload.client_ref, body: String(payload.body || ''), replyTo: payload.reply_to || null }), err))
    schedule()
  }
  /** The relay took a send: its line shows until the host's copy comes back. */
  function track(payload: SendPayload) {
    if (find(payload.client_ref)) return
    payloads.set(payload.client_ref, payload)
    put(sentLine(newLine({ clientRef: payload.client_ref, body: String(payload.body || ''), replyTo: payload.reply_to || null })))
  }
  /** Send again on a failed line: a fresh round at once, the same client_ref. */
  async function again(ref_: string) {
    const l = find(ref_)
    if (!l) return
    put({ ...l, state: 'waiting', tries: 0, secondsLeft: 0, error: undefined })
    await attempt(ref_)
    schedule()
  }
  function settle(messages: Array<{ client_ref?: string | null }>) {
    const next = settleLines(lines.value, messages)
    if (next !== lines.value) {
      for (const l of lines.value) if (!next.includes(l)) payloads.delete(l.clientRef)
      lines.value = next
    }
  }
  function dispose() { if (timer) { clearTimeout(timer); timer = null } }

  return { lines, take, track, again, settle, dispose }
}
