// V0667 static pages (order gwo_a9f121caa4138ec9b369814c): the pages are made from the source alone. Modules that open a socket or fetch at
// import or setup time (the realtime store, the API client) meet these stand-ins and fail at once, so nothing reaches any registry; the
// generator also runs in a network namespace with no interfaces where the host allows it (scripts/static-pages/generate.mjs).
class NoSocket {
  readyState = 3
  onerror: ((e: unknown) => void) | null = null
  onclose: ((e: unknown) => void) | null = null
  constructor() { queueMicrotask(() => { this.onerror?.({ type: 'error' }); this.onclose?.({ type: 'close', code: 1006 }) }) }
  send() {} close() {} addEventListener() {} removeEventListener() {}
}

class NoXHR {
  readyState = 0
  status = 0
  responseText = ''
  response = null
  onerror: ((e: unknown) => void) | null = null
  onloadend: ((e: unknown) => void) | null = null
  open() { this.readyState = 1 }
  setRequestHeader() {} abort() {} removeEventListener() {}
  getAllResponseHeaders() { return '' }
  getResponseHeader() { return null }
  addEventListener(type: string, cb: (e: unknown) => void) { (this as any)['on' + type] = cb }
  send() { queueMicrotask(() => { this.readyState = 4; this.onerror?.({ type: 'error' }); this.onloadend?.({ type: 'loadend' }) }) }
}

export const NO_NETWORK: Record<string, unknown> = {
  WebSocket: NoSocket, EventSource: NoSocket, XMLHttpRequest: NoXHR,
  fetch: async () => { throw new TypeError('static pages are made without a network') },
}

/** Put the stand-ins on a global object (and its window, when it has one). */
export function installNoNetwork(target: any): void {
  for (const [k, v] of Object.entries(NO_NETWORK)) {
    for (const t of [target, target?.window].filter(Boolean)) {
      try { Object.defineProperty(t, k, { value: v, configurable: true, writable: true }) } catch { /* a frozen global keeps its own */ }
    }
  }
}
