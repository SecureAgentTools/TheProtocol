# TRUNK: per-event settlement of interconnect records

The TRUNK blueprint (telecom) as a TheProtocol Proxy recipe: `proxy.yaml` here, a fake of the legacy
system in `fake/`, run on the sandbox end to end before it shipped.

**The legacy side.** The mediation system rates each interconnect event into its settlement table (`settlement_events`, cursor `event_seq`): the partner carrier's agent, the minutes and the charge.

**On TheProtocol.** Each RATED event is settled as it happens, a payment to the partner's agent under the operator's Cockpit mandate, never above the action's `max_amount` or `per_day`, nor the mandate's limits; finance gets a CSV journal (or ISO 20022 camt.053) of what settled, booked from the registry's own `payment.settled` notice (each line names its settlement), so a payment the proxy refused or the registry held back has no line. A DISPUTED event is neither paid nor booked.

**What it needs.** A Cockpit mandate (`a2a.pay`) issued by the operator's owner, named in `mandate:`; a webhook in the console (Developer, Webhooks) for `payment.settled` to this proxy's receiver (`/in/theprotocol`, its secret as `TP_WEBHOOK_SECRET`), and the proxy agent's DID in the `book-settled` mapping's `when` (the owner's webhook carries every payment of the owner's agents); the agent's IRONKEY spend cap at or under it; the payee agents bonded where the registry enforces the bond. SQLite needs no extra; PostgreSQL, MySQL and SQL Server take the `proxy-sql` extras. Credentials come from the agent's starter files (`.env`, `.env.secret`) by reference;
none is written in the spec.

**Try it locally.** `python fake/fake_mediation.py ./mediation.db --partner-did <the partner's agent> --count 5` rates five events (one DISPUTED). Then:

```
tp-proxy validate proxy.yaml
tp-proxy run proxy.yaml --dry-run            # what it would send, sending nothing (Ctrl-C to stop: a receiver never finishes, so --once does not end here)
tp-proxy run proxy.yaml                        # for real
```

**Check it.** Each payment's settlement is on both agents' records; the journal holds one debit per settled payment, its text the settlement's transaction id; a refused one is in `tp-proxy dead` and not in the journal; the ledgers' supply delta stays 0.
