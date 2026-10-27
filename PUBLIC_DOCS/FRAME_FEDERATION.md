<!-- GENERATED from AgentVault/agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src/assets/docs/operator/15_frame_federation.md by scripts/distribution/gen_public_docs.py. Edit that file, not this copy: the export refuses a copy that differs from its source. -->

# Federating a frame, call by call

**Audience**: the admin of a frame stood up with `frame-up.py`, and the admin of the frame it asks to join
**Checked against the source**: 2026-10-16 (`scripts/distribution/frame-federate.py`, the registry's
`routers/frame_invitations.py` and `services/federation_licence.py`)

Two frames take part. **Your frame** asks; **the peer** answers. Exactly one step needs the peer's admin: approving
the invitation, in Frame Management or over the API. Everything on your side runs from your frame's host, through
`scripts/distribution/frame-federate.py`. This page lists every call both sides make, in the order they happen, so
you can run the flow by script or by hand, and tell from any printed line where a run stopped.

To join the public network, the peer is `https://theprotocol.cloud`: the EU frame, the network's genesis. In the
commands below:

| Placeholder | Meaning | Example |
|---|---|---|
| `<name>` | your frame's name (the container prefix) | `myframe` |
| `<stack-root>` | where frame-up puts stacks and secrets | `/opt/theprotocol/stack` |
| `<stack>` | your frame's stack directory | `/opt/theprotocol/stack/myframe-<ts>` |
| `<port>` | your registry's loopback port (the stack's compose publishes it on 127.0.0.1) | `8500` |
| `<you>` | your frame's public name (its trust domain) | `frame.example.org` |
| `<peer>` | the peer's console URL | `https://peer.example.org` |
| `<peer-td>` | the peer's trust domain, read from its card | `peer.example.org` |
| `<id>` | the invitation id the peer assigns | `16793e5c-f97d-4e65-8775-edf8b703bfb7` |

## Before you start

- Your frame is up and healthy (`frame-up.py` finished and printed its console).
- You have the admin secret file `frame-up.py` wrote: `<stack-root>/<name>-secrets/.<name>_frame_admin.secret.json`.
- The peer can reach your three machine lanes from the internet: the federation gateway (8443), the SPIRE bundle
  endpoint (8444) and the ledger gateway (8445), or the ports you moved them to with frame-up's port flags. The peer
  dials the bundle endpoint twice (when it stores your invitation, and when its admin approves) and the federation
  gateway for the callback and every later card pull.
  To see it from outside before you invite anyone, run `scripts/distribution/frame-reach.py --public-name <you>`
  (frame-up.py runs it at its end): the network dials your console and the three lanes back and prints, for every
  lane that does not answer, the one thing to fix. The usual causes are the router's port forwarding, the provider's
  firewall and the A record; the host firewall rarely is, because Docker publishes the lanes past it.
- The peer's admin holds the `admin_federation` flag on the peer.
- Where the peer enforces network licences (the production frames do), your frame needs a network licence before the
  peer can approve (the network licence, below).
- You are root on your frame's host: the script runs `docker exec` and `docker cp` on your frame's containers.

## The whole flow

| Step | Who | Call |
|---|---|---|
| 1 | your host | read `<stack>/.env.frame-test` and `<stack>/docker-compose.frame-test.yml` |
| 2 | your host → peer | `GET <peer>/.well-known/registry-card.json` |
| 3 | your host → peer | `GET <the peer's bundle endpoint>` |
| 3 | your host → your SPIRE server | `bundle set`, `federation create`, `entry show`, `entry update` for each service entry |
| 4 | your host | wait until your frame's TLS terminators carry the peer's roots |
| 5 | your host → your registry | `POST /api/v1/auth/login`, `GET /api/v1/admin/federation/frame-invitations?status=all&limit=200`, `POST /api/v1/admin/federation/frame-invitations/outbound` |
| 5 | your registry → peer | `POST <peer>/api/v1/federation/frame-invitations` |
| 5 | peer → your bundle endpoint | `GET https://<you>:8444/` (the peer checks it answers before it stores the invitation) |
| 6 | **peer's admin** | Frame Management, Pending Invitations, **Approve**, then **Approve + Federate** (or the API call below) |
| 6 | peer's admin → peer | `POST /api/v1/admin/federation/frame-invitations/<id>/approve` |
| 6 | peer → your bundle endpoint | `GET https://<you>:8444/` |
| 6 | peer → its own SPIRE server | `bundle set`, `entry update` for each service entry, `federation create` |
| 6 | peer → your federation gateway | `POST https://<you>:8443/api/v1/federation/frame-invitations/<id>/finalize` (mutual TLS) |
| 6 | peer → its own ledger | `POST /api/v1/admin/cross-frame-peers`, `POST /api/v1/admin/federation-operators` |
| 7 | your host → your registry | `GET /api/v1/admin/federation/frame-invitations/<id>` every 5 s until `completed` |
| 8 | your host → your registry | `GET /api/v1/admin/federation/frame-invitations/<id>/licence-key` (once) |
| 8 | your host | write `FEDERATION_LICENSE_KEY` into `<stack>/.env.frame-test`, recreate your registry alone |

The script prints steps 1 to 5 as `[1/7]` to `[5/7]`, the wait and its outcome as `[6/7]`, and the licence as
`[7/7]`. The one command:

```bash
cd scripts/distribution
./frame-federate.py --stack-dir <stack> --with <peer> \
    --admin-secret-file <stack-root>/<name>-secrets/.<name>_frame_admin.secret.json
```

Options: `--dry-run` reads your frame and the peer's card and prints the SPIRE commands it would run, touching
nothing. `--contact-email` and `--description` are what the peer's admin reads (defaults: your frame admin's email,
and "outbound invitation to `<peer>`"). `--peer-bundle-endpoint` overrides the address the peer's card advertises.
`--timeout-min` (20) is how long step 7 waits for the approval. `--fresh` sends a new invitation instead of resuming
an earlier one. `--no-licence` stops before step 8. The secret file can also come from `FRAME_ADMIN_SECRET_FILE`.

## Your side, step by step

### 1. Read your frame's facts

No network. From `.env.frame-test` and the rendered compose the script takes your frame's name, trust domain, SPIRE
server container (`<name>-spire-server`), the registry's loopback port, and the four containers that terminate TLS
with your frame's certificates (`<name>-nginx-federation`, `<name>-nginx-teg`, `<name>-nginx-event-store` and
`<name>-registry`).

```
[1/7] frame myframe: trust domain frame.example.org, SPIRE myframe-spire-server, registry 127.0.0.1:8500, terminators myframe-nginx-federation, myframe-nginx-teg, myframe-nginx-event-store, myframe-registry
```

### 2. Read the peer's card

```bash
curl -s <peer>/.well-known/registry-card.json | \
  python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["identity"]["trust_domain"], d["federation"]["spire_bundle_endpoint"])'
```

The card names the peer's trust domain and its public SPIRE bundle endpoint. The script refuses (exit 2, nothing
touched) when `--with` is not an https console that serves a card, when the card names your own trust domain, or when
the bundle endpoint is missing, not https, a docker-internal name, a name that does not resolve, or a name that
resolves only to loopback here. `--dry-run` stops here.

```
[2/7] peer peer.example.org: bundle endpoint https://peer.example.org:8444/ (from the peer's card); the relationship will dial https://peer.example.org:8444 as spiffe://peer.example.org/spire/server
```

### 3. Trust the peer's root in your SPIRE server

```bash
# the peer's bundle (a JWK set; see "Why the bundle fetch does not verify TLS" below)
curl -sk <the peer's bundle endpoint> -o /tmp/peer.bundle
# the SPIRE image has no shell, so the file goes in with docker cp
docker cp /tmp/peer.bundle <name>-spire-server:/tmp/frame_bundle_<peer-td>.spiffe
docker exec <name>-spire-server /opt/spire/bin/spire-server bundle set \
    -id spiffe://<peer-td> -path /tmp/frame_bundle_<peer-td>.spiffe -format spiffe
# the relationship keeps that bundle fresh after the peer rotates its CA
docker exec <name>-spire-server /opt/spire/bin/spire-server federation list
docker exec <name>-spire-server /opt/spire/bin/spire-server federation create \
    -trustDomain <peer-td> -bundleEndpointURL <the bundle endpoint, scheme and host:port only> \
    -bundleEndpointProfile https_spiffe -endpointSpiffeID spiffe://<peer-td>/spire/server
# every service and operator entry must federate with the peer, or its certificates will not carry the peer's root
docker exec <name>-spire-server /opt/spire/bin/spire-server entry show
```

Then one `entry update` per entry whose SPIFFE ID path starts with `service/` or `operator/`, except `service/data`
(your databases' identity is never federated). `entry update` replaces the entry, so it must carry everything the
entry already has: `-entryID`, `-spiffeID`, `-parentID`, every `-selector`, `-x509SVIDTTL`, every `-dns`, every
`-federatesWith` it already lists, and the new `-federatesWith spiffe://<peer-td>`. The script builds these from
`entry show`; by hand, copy each entry's fields exactly.

```
[3/7] bundle for peer.example.org: 2659 bytes (spiffe), set into myframe-spire-server; relationship create (https://peer.example.org:8444, https_spiffe); workload entries updated 6, already 0, skipped 1
```

When your SPIRE server already held the peer's root, the line says `(root already held)` and step 4 has nothing to
wait for.

### 4. Wait for the new roots to reach your terminators

Your cert-writers copy the trust bundle into `/certs/bundle.0.pem` on their own cycle (`FT_CW_REFRESH_SEC`, 300 s by
default). The script counts certificates in each terminator until every count has grown, and gives up after two
cycles plus 30 s (exit 4; re-run it, every step is idempotent):

```bash
docker exec <name>-nginx-federation grep -c "BEGIN CERT" /certs/bundle.0.pem
```

```
[4/7] roots: myframe-nginx-federation 1->3, myframe-nginx-teg 1->3, myframe-nginx-event-store 1->3, myframe-registry 1->3
```

Each count grows by the number of X.509 roots the peer publishes: two while its CA rotates, as in this example.

### 5. Send the invitation

The script logs in as your frame admin over loopback, looks for an earlier outbound invitation to the same peer
(a re-run resumes it instead of sending a second one), and asks your own registry to send the invitation:

```bash
# form-encoded, not JSON
TOKEN=$(curl -s -X POST http://127.0.0.1:<port>/api/v1/auth/login \
  --data-urlencode "username=<admin email>" --data-urlencode "password=<admin password>" | \
  python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:<port>/api/v1/admin/federation/frame-invitations?status=all&limit=200"

curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  http://127.0.0.1:<port>/api/v1/admin/federation/frame-invitations/outbound \
  -d '{"target_registry_url": "<peer>", "contact_email": "<admin email>",
       "description": "outbound invitation to <peer>", "spire_bundle_imported": true}'
```

Your registry then makes the call the peer receives. It is public, rate-limited to 5 per hour per address, and
carries only your frame's public facts, a one-time nonce and your frame's licence-signing public key:

```
POST <peer>/api/v1/federation/frame-invitations
{"trust_domain": "<you>", "bundle_endpoint_url": "https://<you>:8444/", "federation_endpoint_url": "https://<you>:8443",
 "event_store_url": "https://<you>:8445", "name": "<display name>", "contact_email": "...", "description": "...",
 "initiator_nonce": "<32 hex characters>", "licence_key": {"kty": "OKP", "crv": "Ed25519", "x": "..."}}
```

A frame that already holds a network licence also sends it (`licence_certificate`, `licence_chain`). Before it stores
the invitation, the peer fetches your bundle endpoint once. It answers 201 with the invitation's id, and your registry
records its outbound row under that same id, so the peer's callback in step 6 finds it. `spire_bundle_imported: true`
tells your registry that step 3 already trusted the peer, so the callback does not touch your SPIRE server (a kit
frame's registry holds no Docker socket).

```
[5/7] outbound invitation 16793e5c-f97d-4e65-8775-edf8b703bfb7 sent to https://peer.example.org and recorded on this frame (status pending); the peer's admin now approves it in Frame Management
```

What the peer can answer, as your outbound call reports it (HTTP 502 with the peer's answer inside): 422 when your
bundle endpoint could not be fetched from the peer or your trust domain equals the peer's; 409 when an invitation
from your trust domain is already pending there; 429 after 5 invitations in an hour; 503 when the peer runs with
`FRAME_INVITATIONS_PUBLIC_DISABLED` set. Your own registry answers 400 when it does not know its own public lanes
(`SPIRE_TRUST_DOMAIN`, `FRAME_LOCAL_BUNDLE_ENDPOINT_URL`, `BILATERAL_PEER_URL`).

## The peer's side: the approval

### 6. Approve (the one step on the peer)

The peer's admin opens **Frame Management**. The invitation is in **Pending Invitations** with your frame's name,
trust domain, federation endpoint, contact, source address and the time it arrived. **Approve** opens a dialog that
lists what approval does and takes an optional note; **Approve + Federate** runs it.

The same approval without a browser, with an admin token from the peer (`POST /api/v1/auth/login` on the peer):

```bash
curl -s -H "Authorization: Bearer $PEER_TOKEN" "<peer>/api/v1/admin/federation/frame-invitations"
curl -s -X POST -H "Authorization: Bearer $PEER_TOKEN" -H "Content-Type: application/json" \
  "<peer>/api/v1/admin/federation/frame-invitations/<id>/approve" -d '{"notes": ""}'
# reject instead:  POST .../frame-invitations/<id>/reject  {"reason": "..."}
```

The listing shows pending invitations unless it is asked for another status (`?status=all`). Over MCP the same calls
are `listAdminFrameInvitations` (pending only), `approveFrameInvitation` and `rejectFrameInvitation`.

Approving runs these on the peer, in this order:

1. `GET https://<you>:8444/`: your bundle.
2. Your bundle into the peer's SPIRE server (`bundle set`), then every service entry federates with you
   (`entry update ... -federatesWith spiffe://<you>`), then the relationship (`federation create`, https_spiffe,
   dialing `https://<you>:8444`).
3. A peer row for your frame (type `frame`, status `ACTIVE`, dialing `https://<you>:8443`) and a federation licence
   for your frame. The peer stores only the licence's hash. A genesis approving with a plan also issues your network
   licence here.
4. The callback to your frame, over mutual TLS (when that leg fails, the peer tries your public console without a
   client certificate; the nonce authenticates the call):
   ```
   POST https://<you>:8443/api/v1/federation/frame-invitations/<id>/finalize
   {"approver_trust_domain": "<peer-td>", "approver_bundle_endpoint_url": "...", "approver_name": "...",
    "approver_bundle_pem": "<the peer's bundle>", "nonce_echo": "<your nonce>",
    "approver_federation_endpoint_url": "https://<peer-td>:8443", "federation_license_key": "<the licence, once>"}
   ```
   A network licence issued at this approve rides along (`licence_certificate`, `licence_chain`). Your registry checks
   the nonce (403 on a mismatch, 409 when already completed), records a peer row for the peer, installs a delivered
   network licence, holds the licence key for one hour for step 8, and marks the invitation `completed`.
5. Two registrations on the peer's own ledger: your frame as a cross-frame peer (`POST /api/v1/admin/cross-frame-peers`,
   so its event store replicates yours) and as a federation operator (`POST /api/v1/admin/federation-operators`, so
   cross-frame votes weigh it).
6. Mail to your contact address ("Frame Federation Approved") and to the peer's admin address.

The dialog closes with **Frame Federated** when all of it worked. **Frame Approved (partial)** means the handshake
worked and one of the two ledger registrations did not: the peer's admin presses **Resync** on your row to run them
again. **Approval Partial** means the callback to your frame failed: `POST .../frame-invitations/<id>/finalize-retry`
(MCP `finalizeRetryFrameInvitation`) sends it again once your federation gateway answers; a retry issues a new
licence key, because the first one never arrived.

### The network licence

A peer that enforces network licences (`FEDERATION_LICENCE_MODE=enforce`; the production frames do, and their public
`GET /api/v1/federation/licence/verdicts` says `"mode": "enforce"`) refuses the approve with 403 unless your frame
presents a network licence it can verify. Only the network's genesis issues one, and it can do so in the same approve:
its admin approves with a plan in the body,

```bash
curl -s -X POST -H "Authorization: Bearer $PEER_TOKEN" -H "Content-Type: application/json" \
  "<peer>/api/v1/admin/federation/frame-invitations/<id>/approve" -d '{"notes": "", "network_licence_plan": "private"}'
```

The plans are `founding`, `private`, `educational`, `research` and `non-profit` (no end date) and `enterprise` and
`government` (365 days); `network_licence_days` sets another term. The licence goes to the licence-signing key your
invitation carried, and the callback delivers it. Frame Management's **Approve** and the MCP tool send no plan, so an
approve that must issue the network licence goes over the API. A frame stood up with the kit does not enforce licences
itself (`FEDERATION_LICENCE_MODE` is `off` unless you set it).

## Your side again

### 7. Wait for completed

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:<port>/api/v1/admin/federation/frame-invitations/<id>
```

The script polls every 5 s for up to `--timeout-min` minutes. `pending` means the peer's admin has not approved yet;
exit 4 leaves everything in place and a re-run resumes at this wait. A rejection does not reach your frame: the peer
mails your contact address with its reason and your row stays `pending`, so the wait times out. After a rejection,
`--fresh` sends a new invitation.

```
    invitation 16793e5c-f97d-4e65-8775-edf8b703bfb7: pending
    invitation 16793e5c-f97d-4e65-8775-edf8b703bfb7: completed
[6/7] completed at 2026-09-19T11:36:11.686328Z: peer row id=1 name=Peer url=https://peer.example.org:8443; licence prefix tp_fed_41aa9
```

A 401 during the wait means your admin session ended (a password change, or a logout of the same account anywhere,
ends every session of that account): re-run the command.

### 8. Apply the licence

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:<port>/api/v1/admin/federation/frame-invitations/<id>/licence-key
```

The key is handed out once, within an hour of the callback. The script writes it into `<stack>/.env.frame-test` as
`FEDERATION_LICENSE_KEY` (the file keeps its mode, 600), recreates the registry alone, waits for it to be healthy,
and checks that the variable is set inside it. It never prints the key.

```bash
docker compose -f <stack>/docker-compose.frame-test.yml --env-file <stack>/.env.frame-test \
    up -d --no-deps --no-build --force-recreate <name>-registry
```

```
[7/7] licence tp_fed_41aa9... applied: FEDERATION_LICENSE_KEY written to .env.frame-test, the registry recreated alone and healthy, the variable present in its environment
```

## After federation

These happen on their own; nobody runs them.

- **Agent cards mirror both ways** on the card pull cycle. `POST /api/v1/federation/sync/trigger` (an admin token;
  at most one call every 30 seconds) starts a cycle now.
- **Each frame lists the other** in `GET /api/v1/federation/registries` and in Frame Management's Federated Frames.
- **Each frame registers the other's TEG as a partner** on its own side of the handshake (the approving frame when it
  approves, your frame when the invitation completes), so a leg between the two TEGs passes the partner rule (see
  TEG-to-TEG trust below).
- **The peer reads your published policy** (`GET https://<you>:8443/api/v1/federation/policy-compliance`) to record
  its first-sight baseline, 45 s after approval and then every 6 hours.
- **The peer refreshes your trust weight** on its ledger on every federation sync cycle
  (`FEDERATION_SYNC_INTERVAL_SECONDS`, 30 s on a kit frame).

How to check it worked:

```bash
# each frame's view of the other (both public)
curl -s http://127.0.0.1:<port>/api/v1/federation/registries
curl -s <peer>/api/v1/federation/registries
# the peer's cards stored on your frame: the default listing is what your frame holds;
# include_federated=true would ask the peers live instead
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:<port>/api/v1/agent-cards/?include_card_data=true&limit=100"
# your ledger still conserves supply (delta 0.0); the port is "es" under "ports" in <stack>/frame-up.json
curl -s http://127.0.0.1:<ledger port>/api/v1/projections/supply-audit
```

A transfer from your frame to an agent on a frame with another unit is refused with HTTP 409 while your frame's FX
switch is off (`FX_ENABLED`, off on a frame stood up alone): "Cross-currency transfer MYF->ECU requires the FX swap
booth, which is disabled (FX_ENABLED=false)". The refusal still shows that the transfer found the peer and its unit:
nothing moved, and both ledgers stay at delta 0.0. Cross-frame FX is described in the Sovereign Frames chapter.

## TEG-to-TEG trust

A transfer to a frame with another unit travels the FX route: your registry moves the units through both frames' FX
reserves (the Sovereign Frames chapter), and the partner rule does not touch it. A leg between two TEGs (a transfer
between frames that share a unit, and every transfer between a frame and its own cloud operators) runs only with a peer
the TEG holds as a current partner: the partner rule (`CROSS_TEG_PARTNER_RULE_MODE`, in the Architecture chapter). The
handshake above sets that trust up on both sides (a frame registers its cloud operators when it provisions them), and a
revoke removes it. A frame you stand up with the kit runs the rule in shadow
(`FT_TEG_CROSS_TEG_PARTNER_RULE_MODE=shadow` in `<stack>/.env.frame-test`): its TEG logs what it would refuse and
refuses nothing while you learn how the trust is set up.

We recommend `enforce` once the trust is proven: transfers to and from your operators and peers have run, and the
TEG's log holds no `WOULD REFUSE` line (its counter `teg_cross_teg_partner_refused_total` stays at 0). Then, from
`<stack>`:

```bash
docker logs <name>-teg 2>&1 | grep -c "WOULD REFUSE"     # 0 once the trust with every peer is in place
sed -i 's/^FT_TEG_CROSS_TEG_PARTNER_RULE_MODE=.*/FT_TEG_CROSS_TEG_PARTNER_RULE_MODE=enforce/' .env.frame-test
docker compose -f docker-compose.frame-test.yml --env-file .env.frame-test up -d --no-deps --force-recreate <name>-teg
```

Under `enforce` a leg with a TEG that is not a partner is refused before anything moves (`cross_teg_partner_refused`;
the peer that called gets HTTP 403). `shadow` again is the same line with `shadow`.

## Why the bundle fetch does not verify TLS

A SPIRE bundle endpoint presents a certificate from its own SPIRE CA, which no public CA signs, so an https client
that verifies against the public roots cannot fetch it. Both sides fetch the other's bundle without verification:
your script in step 3, the peer's registry in step 6. What the fetch returns is exactly what `bundle set` is told to
trust, so the address is the trust decision. Take it from the peer's card over https (step 2), or from the peer's
admin directly.

## How long it takes

In a measured run, a kit frame federating with a sandbox frame: the invitation was stored about 80 seconds after the
peer's root was trusted. Once the peer's admin pressed **Approve + Federate**, the callback landed within a
second, the registry was recreated with its licence 15 seconds later, and each frame held the other's cards about
seven minutes after the approval.

## Exit codes of `frame-federate.py`

| Code | Meaning | What to do |
|---|---|---|
| 0 | federated, licence applied | nothing |
| 2 | refused before touching anything | the printed sentence names what is missing |
| 3 | a step failed | the sentence names the step and the log to read; fix it and re-run |
| 4 | a wait timed out | re-run later; it resumes where it stopped |
