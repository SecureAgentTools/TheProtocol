// V0663 — recompute a workflow's receipt chain in the browser, so a person need not take the server's word.
// link n: receipt = sha256(prev + '|' + step + '|' + output_hash); the first prev is 64 zeros (services/workflow_rules.py).
import type { ChainLink } from '@/services/api/workflows'

export const GENESIS = '0'.repeat(64)

async function sha256Hex(text: string): Promise<string> {
  const bytes = new TextEncoder().encode(text)
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(digest)).map(b => b.toString(16).padStart(2, '0')).join('')
}

export async function verifyChain(chain: ChainLink[]): Promise<{ ok: boolean; why: string | null }> {
  let prev = GENESIS
  for (let i = 0; i < chain.length; i++) {
    const link = chain[i]
    if (link.prev !== prev) return { ok: false, why: `link ${i + 1} (${link.step}) does not follow the one before it` }
    if ((await sha256Hex(`${prev}|${link.step}|${link.output_hash}`)) !== link.receipt) {
      return { ok: false, why: `link ${i + 1} (${link.step}) does not match its own hash` }
    }
    prev = link.receipt
  }
  return { ok: true, why: null }
}
