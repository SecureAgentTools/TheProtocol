/**
 * POCKET NFC (2026-07-09) — tap-to-pay / tap-to-request over Web NFC (NDEF, the NFC Forum
 * standard — the "most used" NFC data format).
 *
 * HONEST SCOPE: a PWA cannot emulate an EMV card (no HCE) — card-terminal payments need the
 * native wrapper (S1 Capacitor) AND a card network, and are the wrong rail for AVT anyway.
 * What ships here is the real, standards-based thing a phone-to-phone token economy wants:
 *   • PAY:     scan an NDEF tag/phone → parse the payment-request URI → Send sheet prefilled
 *              → biometric confirm → smartSend. (Web NFC: Android Chrome; feature-detected.)
 *   • REQUEST: write the payment-request URI to any NFC tag (merchant-sticker pattern).
 *              iPhones can't run Web NFC but READ NDEF tags natively → the https URI opens
 *              Pocket with the payment prefilled — graceful iOS path, zero extra code.
 *   • The SAME URI rides the Receive QR → any camera app is a fallback "reader".
 *
 * Payment Request URI v1 (registry-agnostic — only the hash route matters):
 *   https://<any-registry>/ui#/pocket/pay?to=<did>&amount=<dec>&ccy=<code>&memo=<text>
 *   `to` required; the rest optional.
 */
import { ref } from 'vue'
import { useI18n } from '@/composables/useI18n'

const supported = ref(typeof window !== 'undefined' && 'NDEFReader' in window)
const scanning = ref(false)
const writing = ref(false)
let abortCtl: AbortController | null = null

export interface PayRequest { to: string; amount?: string; ccy?: string; memo?: string }

export function buildPayUri(req: PayRequest): string {
  const base = `${location.origin}/ui#/pocket/pay`
  const q = new URLSearchParams()
  q.set('to', req.to)
  if (req.amount) q.set('amount', req.amount)
  if (req.ccy) q.set('ccy', req.ccy)
  if (req.memo) q.set('memo', req.memo)
  return `${base}?${q.toString()}`
}

/** Parse a payment-request URI (or a bare DID, for old QR codes). Null if not one of ours. */
export function parsePayUri(s: string): PayRequest | null {
  const t = (s || '').trim()
  if (t.startsWith('did:')) return { to: t }  // legacy bare-DID QR
  const m = t.match(/#\/pocket\/pay\?(.+)$/)
  if (!m) return null
  const q = new URLSearchParams(m[1])
  const to = q.get('to') || ''
  if (!to.startsWith('did:')) return null
  return { to, amount: q.get('amount') || undefined, ccy: q.get('ccy') || undefined, memo: q.get('memo') || undefined }
}

export function usePocketNfc() {
  const { t } = useI18n()
  /** Scan for a payment request. Resolves with the parsed request, or null on stop/error. */
  async function scanPayRequest(onStatus?: (s: string) => void): Promise<PayRequest | null> {
    if (!supported.value) return null
    stopScan()
    scanning.value = true
    abortCtl = new AbortController()
    try {
      const reader = new (window as any).NDEFReader()
      await reader.scan({ signal: abortCtl.signal })
      onStatus?.(t('pocket.nfc.holdNear', 'Hold near the payment tag…'))
      return await new Promise<PayRequest | null>((resolve) => {
        abortCtl!.signal.addEventListener('abort', () => resolve(null))
        reader.addEventListener('readingerror', () => onStatus?.(t('pocket.nfc.readError', 'Could not read that tag — try again.')))
        reader.addEventListener('reading', (ev: any) => {
          try {
            for (const rec of ev.message.records) {
              let text = ''
              if (rec.recordType === 'url' || rec.recordType === 'absolute-url') {
                text = new TextDecoder().decode(rec.data)
              } else if (rec.recordType === 'text') {
                text = new TextDecoder(rec.encoding || 'utf-8').decode(rec.data)
              }
              const req = parsePayUri(text)
              // resolve BEFORE stopScan: abort() fires this promise's abort-listener (resolve(null))
              // synchronously — resolving first wins the race (a promise settles once).
              if (req) { resolve(req); stopScan(); return }
            }
            onStatus?.(t('pocket.nfc.noRequest', 'Tag read, but no payment request on it.'))
          } catch { onStatus?.(t('pocket.nfc.unreadable', 'Unreadable tag.')) }
        })
      })
    } catch (e: any) {
      onStatus?.(e?.name === 'NotAllowedError' ? t('pocket.nfc.denied', 'NFC permission denied.') : t('pocket.nfc.unavailable', 'NFC unavailable (is it enabled?).'))
      return null
    } finally { scanning.value = false }
  }

  function stopScan() { try { abortCtl?.abort() } catch {} ; abortCtl = null; scanning.value = false }

  /** Write a payment request to an NFC tag (NDEF url record — readable by ANY phone's OS). */
  async function writePayRequest(req: PayRequest, onStatus?: (s: string) => void): Promise<boolean> {
    if (!supported.value) return false
    writing.value = true
    try {
      const reader = new (window as any).NDEFReader()
      onStatus?.(t('pocket.nfc.holdWritable', 'Hold a writable NFC tag to the phone…'))
      await reader.write({ records: [{ recordType: 'url', data: buildPayUri(req) }] })
      onStatus?.(t('pocket.nfc.written', 'Payment request written to the tag.'))
      try { (navigator as any).vibrate?.([8, 40, 8]) } catch {}
      return true
    } catch (e: any) {
      onStatus?.(e?.name === 'NotAllowedError' ? t('pocket.nfc.denied', 'NFC permission denied.') : t('pocket.nfc.writeFailed', 'Write failed — tag missing or locked.'))
      return false
    } finally { writing.value = false }
  }

  return { supported, scanning, writing, scanPayRequest, stopScan, writePayRequest }
}
