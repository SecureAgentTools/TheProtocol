# BAZAAR: inventory, and fulfilment only on a received payment

The BAZAAR blueprint (marketplace) as a TheProtocol Proxy recipe: `proxy.yaml` here, a fake of the legacy
system in `fake/`, run on the sandbox end to end before it shipped.

**The legacy side.** The shop posts inventory changes, HMAC-signed with `SHOP_HMAC`, to `/in/shop`; the warehouse system takes fulfilment releases on its API.

**On TheProtocol.** Each inventory change becomes a `bazaar.inventory_level` attestation. TheProtocol's own `payment.received` webhook (signed by the registry) is forwarded to the WMS with the payer, the amount and the ledger transaction: the WMS fulfils only what has been paid, and a payment that never settles never reaches it.

**What it needs.** An agent with the `attestor` role; a webhook for `payment.received` registered in the console (Developer, Webhooks) pointing at the proxy's `/in/theprotocol`, its secret as `TP_WEBHOOK_SECRET`, and the shop agent's DID in the `paid-release` mapping's `when` (the owner's webhook carries the income of every agent the owner has); `SHOP_HMAC`, `WMS_HMAC`, and the WMS endpoint in the sink's `url`. Credentials come from the agent's starter files (`.env`, `.env.secret`) by reference;
none is written in the spec.

**Try it locally.** `python fake/mock_wms.py --listen 127.0.0.1:8721` is a WMS; `python fake/fake_shop.py http://127.0.0.1:8711/in/shop --count 4` posts four inventory changes. Then:

```
tp-proxy validate proxy.yaml
tp-proxy run proxy.yaml --dry-run            # what it would send, sending nothing (Ctrl-C to stop: a receiver never finishes, so --once does not end here)
tp-proxy run proxy.yaml                        # for real
```

**Check it.** The WMS's file (`wms-received.jsonl`) holds one release per payment received.
