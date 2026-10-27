/**
 * What a send preview says arrives (Pocket's send sheet), from the smart-send dry run.
 *
 * §FESUITE (2026-10-10, lifecycle 81 on the sandbox): a cross-frame FX send whose dry run carried no quote fell to the
 * same-currency reading (0.5% off, in the SENDER's currency) and promised "≈ 0.9950 SBXB" for money that arrives as
 * SBXA. An FX route arrives in the RECEIVER's currency: with a quote, its estimate; without one, the unit and no number
 * (the rate is set when it is sent). Never the wrong unit.
 */
export interface SendArrival {
  /** the estimate as a decimal string; '' when the route names no number (an FX route without a quote) */
  amt: string | null
  ccy: string
}

export function sendArrival(p: any): SendArrival | null {
  if (!p || !p.method) return null
  if (p.method === 'fx') {
    if (p.fx_quote?.est_received) return { amt: String(p.fx_quote.est_received), ccy: String(p.currency_received || '') }
    return { amt: '', ccy: String(p.currency_received || '') }
  }
  const n = Number(p.amount || 0)
  if (p.method === 'local') {
    // local: the receiver gets the FULL amount; the sender pays the network fee on top (measured live: 5 sent ->
    // +5.000000 received, sender -5.025)
    return { amt: n ? n.toFixed(4) : null, ccy: String(p.currency_sent || '') }
  }
  // same-currency cross-registry: the 0.5% rail fee lands on the receiver's side
  const r = n * 0.995
  return { amt: r ? r.toFixed(4) : null, ccy: String(p.currency_sent || '') }
}
