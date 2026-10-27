/**
 * services/walletAgent.ts — §WALLETAGENT (2026-09-02)
 *
 * ONE place for what a "wallet agent" is, so no surface drifts. His framing: the FIRST agent
 * a person creates is their wallet agent — an identity that holds and moves funds. Funds can
 * always be transferred from it to a later, more capable agent, and the identity itself can
 * be reused by an agent of the person's choice (same DID, same ledger account, same history).
 *
 * The marker is a card fact, not a new agent type: `card_data.tags` includes `wallet`.
 * A wallet card keeps the quick path's placeholder endpoint because the A2A validator
 * requires one; §CHATCOHERE's answerable-only discover filter already hides such cards.
 */
export const WALLET_TAG = 'wallet'

/** True when a card (or a list row carrying `card_data`) is tagged as a wallet agent. */
export function isWalletAgent(rowOrCard: any): boolean {
  if (!rowOrCard) return false
  const card = rowOrCard.card_data && typeof rowOrCard.card_data === 'object' ? rowOrCard.card_data : rowOrCard
  const tags = Array.isArray(card?.tags) ? card.tags : []
  return tags.some((t: any) => String(t).toLowerCase() === WALLET_TAG)
}

/** The tags a wallet agent's card carries at birth. */
export function walletTags(): string[] { return [WALLET_TAG] }

/**
 * The explanation, short and analytical, as three sentences. Surfaces pass their `t`
 * so every line is a real key in every bundle; the English here is the fallback.
 */
export function walletSentence(t: (k: string, fb: string) => string): string[] {
  return [
    t('wallet.what', 'An agent is an identity on this registry: a DID, credentials and a ledger account. It does not have to be software.'),
    t('wallet.first', 'Your wallet agent is your first identity. It holds your funds and pays and votes with its own address, under your name.'),
    t('wallet.later', 'Later, create more capable agents and move funds to them with one transfer, or run your own agent with this identity\'s credentials: it becomes that agent, balance and history included.'),
  ]
}

/** The four "how it works" lines the success sheet and the tours fold open. */
export function walletHowItWorks(t: (k: string, fb: string) => string): string[] {
  return [
    t('wallet.how.identity', 'Identity: a DID with credentials. Anything you do as it is signed as it.'),
    t('wallet.how.funds', 'Funds: its ledger account holds what you are granted, paid or sent; paid calls draw on it.'),
    t('wallet.how.move', 'Move: one transfer sends funds to any agent you create later.'),
    t('wallet.how.reuse', 'Reuse: put its credentials into an agent you run and that agent is this identity, balance and history included.'),
  ]
}

/** The first agent becomes the wallet only when the person's agents were READ and are none (§FESUITE, V0577): a read
 *  that failed is not "no agents"; taken as one, it made a hidden "first wallet" for a person who has agents. */
export function firstAgentIsWallet(agents: readonly unknown[], readFailed: boolean): boolean {
  return !readFailed && agents.length === 0
}

/** The ONE send door, prefilled to move funds into a newer agent (D3: one send door). */
export function moveFundsDoor(toDid: string): string {
  return `/pocket/pay?to=${encodeURIComponent(toDid)}`
}
