# Run canaries on your frame

A canary is a synthetic transfer that your frame makes to itself, on a fixed cadence, so that a broken lane tells you
rather than a user. Each fire is a real transfer by a real agent over the rail your users use: a canary that passes
shows that an agent can still sign in, move units, settle the transfer and have it recorded in the ledger, end to end,
right now.

Canaries move **real units on every fire**. They never issue: units go from agent to agent, fees go to the fee
collector, and the rebalancer moves units between the treasury and the canaries, so your supply delta stays 0.0. Read
"What it costs, and how to keep it from draining your frame" before you pick amounts, especially on a frame whose
supply is small.

## What you need

- **A frame stood up with `frame-up.py`**, and its admin login (in the frame's secrets directory). A cluster of a frame
  plus its cloud operators works the same way, with one extra step for the operators.
- **Your frame's database**, for a few `INSERT`s. There is no admin rail that creates canary agents or paths; the
  runner reads them from the registry's own database. On a kit frame:
  `docker exec -i <name>-db psql -U registry -d frame_test_registry -v ON_ERROR_STOP=1`.

## The shape

Each **frame** is the cockpit for itself and for its own cloud operators:

- the frame schedules its own paths and dispatches its operators' paths to them over the federation channel
  (`CANARY_RUNNER_MODE=master`),
- an operator never schedules anything itself; it fires only what its frame dispatches
  (`CANARY_RUNNER_MODE=follower`), with its own agents and its own credentials, which never leave it.

A registry with no operators can stay in the default mode, `local`: it schedules and fires its own paths and
dispatches nothing. An operator trusts its parent frame's identity and nobody else's, so a frame cannot be the cockpit
for another frame's operators. Two federated frames with two operators each means **two** masters, not one.

## Step by step

### 1. A service account owns the canaries, never your admin account

A kit frame's standup already created one, `svc-canary`, with exactly the two flags below; its login is in
`<stack-root>/<name>-secrets/.<name>_service_accounts.secret.json`. On a registry without one (a cloud operator, for
instance), create it as that registry's admin:

```bash
# on each registry, as its admin
curl -sX POST "$REG/api/v1/auth/register" -H 'Content-Type: application/json' \
  -d '{"name":"svc-canary","email":"svc-canary@<your-frame>.dev","password":"<generated>","tos_accepted":true}'
# the register answer carries no developer id: ask the server for it
curl -s "$REG/api/v1/admin/developers?search=svc-canary@<your-frame>.dev" -H "Authorization: Bearer $ADMIN_JWT"
curl -sX POST "$REG/api/v1/admin/developers/$DEV_ID/force-email-verify" -H "Authorization: Bearer $ADMIN_JWT"
curl -sX PUT  "$REG/api/v1/admin/developers/$DEV_ID/admin-flags" -H "Authorization: Bearer $ADMIN_JWT" \
  -H 'Content-Type: application/json' \
  -d '{"admin_treasury": true, "agents_unlisted_by_default": true}'
```

Where the registry requires an invite code (`beta_invite_required` in `GET /api/v1/auth/registration-config`),
generate one first (`POST /api/v1/admin/invite-codes/generate` with `{"count": 1, "max_uses": 1}`) and add it to the
registration as `invite_code`. Changing admin flags needs the `admin_platform` flag on your own account.

`admin_treasury` lets the service account fund its own agents from the frame's treasury. `agents_unlisted_by_default`
makes every agent it creates **unlisted**: absent from discovery, the public list, the explore page and the globe, while
still resolvable by DID and still federated (a peer holds an unlisted mirror of its card), which is how a
cross-registry path's sender resolves the agent it pays. A canary is a service agent; nobody should be able to find and
hire it.

### 2. Two agents per registry

Create them as `svc-canary`, through the normal onboarding rail:

```bash
BT=$(curl -sX POST "$REG/api/v1/onboard/bootstrap/request-token" -H "Authorization: Bearer $SVC_JWT" \
     -H 'Content-Type: application/json' -d '{"agent_type_hint":"canary_agent"}' | jq -r .bootstrap_token)
curl -sX POST "$REG/api/v1/onboard/create_agent" -H "Bootstrap-Token: $BT" -H 'Content-Type: application/json' \
  -d '{"agent_did_method":"theprotocol","agent_host":"https://canary-<reg>-sender.agents.local"}'
```

`.agents.local` is a reserved name the card pull-sync never dials, which is what you want for an agent that serves
nothing. Keep the `client_secret` from the response (it is shown once) in a file only root can read, and **read the
card back** (`GET $REG/api/v1/agent-cards/<did>` as `svc-canary`): if `unlisted` is not `true`, stop and fix step 1
rather than continuing with a listed canary.

Do this twice per registry: a *sender* and a *receiver*.

### 3. Prefund both agents

```bash
curl -sX POST "$REG/api/v1/teg/treasury/fund-agent" -H "Authorization: Bearer $SVC_JWT" \
  -H "Idempotency-Key: canary-prefund-<reg>-<short did>" -H 'Content-Type: application/json' \
  -d '{"target_agent_did":"<did>","amount":"25","reason":"canary_prefund"}'
```

Both, not just the sender: the local path runs in both directions.

### 4. The rows

In each registry's own database (`canary_agents`, then `canary_paths`), written **inactive** so nothing fires yet:

```sql
-- this registry's own two agents: real credentials, and localhost as the URL the runner dials
INSERT INTO canary_agents (agent_did, client_id, client_secret, registry_id, registry_url, frame, is_active, prefund_amount, notes)
VALUES ('<sender did>', '<client id>', '<client secret>', 'myframe', 'http://localhost:8000', 'myframe', TRUE, 25, 'svc-canary sender (dark)'),
       ('<receiver did>', '<client id>', '<client secret>', 'myframe', 'http://localhost:8000', 'myframe', TRUE, 25, 'svc-canary receiver (dark)');

-- a reference row for every agent on ANOTHER registry that a path of this one pays: no login happens as it
INSERT INTO canary_agents (agent_did, client_id, client_secret, registry_id, registry_url, frame, is_active, prefund_amount, notes)
VALUES ('<far sender did>', 'receiver-no-login', 'receiver-no-login', 'myoperator', 'myoperator', 'myoperator', TRUE, 0, 'payee on myoperator');

-- the paths: intra stays on this registry, 2pc crosses to another one
INSERT INTO canary_paths (path_id, sender_agent_id, receiver_agent_id, backend, amount, interval_sec, slo_settled_sec, is_active, notes, transport)
VALUES ('myframe-local',      <sender id>,   <receiver id>, 'intra', 0.1, 1800,  60, FALSE, 'canary: local intra', 'bearer'),
       ('myframe-local-back', <receiver id>, <sender id>,   'intra', 0.1, 1800,  60, FALSE, 'canary: the return leg', 'bearer'),
       ('myframe-to-myoperator', <sender id>, <far sender id>, '2pc', 0.1, 1800, 180, FALSE, 'canary: myframe->myoperator', 'bearer');
```

`registry_url = http://localhost:8000` is load bearing: it is how the rebalancer recognises an agent homed on this node
and funds it from **this** node's treasury. A cross-registry path should pay the far registry's **sender** (see the
money section). Give a cross-registry path a longer settle SLO than an intra one.

### 5. The dispatch rows, on the frame only

For every path that lives on one of your operators, tell the frame to schedule it:

```bash
curl -sX POST "$FRAME/api/v1/admin/canary/fleet/remote-paths" -H "Authorization: Bearer $ADMIN_JWT" \
  -H 'Content-Type: application/json' -d '{"paths":[
    {"home_registry":"myoperator","remote_path_id":<the id in the OPERATOR database>,
     "path_label":"myoperator-local","interval_sec":1800,"is_active":false}]}'
```

`home_registry` must match the operator's name in the frame's peer registries (case does not matter): that is how
the dispatcher finds it.

### 6. Probe every lane before you arm anything

As each path's sender, fire exactly what the runner fires, and watch the payee's balance on its own registry:

```bash
JWT=$(curl -sX POST "$REG/api/v1/auth/agent/token" -d "username=<client id>&password=<client secret>" | jq -r .access_token)
# intra
curl -sX POST "$REG/api/v1/teg/transfer" -H "Authorization: Bearer $JWT" -H 'Content-Type: application/json' \
  -d '{"receiver_agent_id":"<payee did>","amount":"0.1","message":"probe"}'
# cross-registry
curl -sX POST "$REG/api/v1/teg/cross-registry-transfer?backend=2pc" -H "Authorization: Bearer $JWT" \
  -H 'Content-Type: application/json' -d '{"receiver_did":"<payee did>","amount":"0.1","message":"probe"}'
```

A `200` that moves no units is a failure. Fix a lane here, where nothing is scheduled yet, rather than after it has
become an alert that fires every half hour.

### 7. Arm, with the runners still off

```bash
curl -sX POST "$FRAME/api/v1/admin/canary/fleet/pause" -H "Authorization: Bearer $ADMIN_JWT"
# set is_active = TRUE on every canary_paths row, and on the frame's dispatch rows (step 5 again, "is_active": true)
curl -sX POST "$FRAME/api/v1/admin/canary/fleet/resume" -H "Authorization: Bearer $ADMIN_JWT"
```

### 8. Turn the switches on, as their own recreate

Set these in the registry's env file and recreate the registry alone
(`docker compose up -d --no-deps --no-build --force-recreate <service>`). **Roll your operators first**, so an operator
is judging results before its frame starts dispatching to it.

On a frame (a master), in `.env.frame-test` (the first six lines are already there, set to `false`):

```
FT_REG_CANARY_ENABLED=true
FT_REG_CANARY_RUNNER_ENABLED=true
FT_REG_CANARY_JUDGE_ENABLED=true
FT_REG_CANARY_VALIDATOR_ENABLED=true
FT_REG_CANARY_REBALANCER_ENABLED=true
FT_REG_CANARY_REFILL_ENABLED=true
CANARY_RUNNER_MODE=master
CANARY_REBALANCER_INTERVAL_SEC=86400
CANARY_REBALANCER_FLOOR_AVT=25
CANARY_REBALANCER_TOPUP_AVT=25
CANARY_REBALANCER_CEILING_AVT=150
```

On a cloud operator (a follower), the same switches under their plain names in its `.env.operator`, with
`CANARY_RUNNER_MODE=follower` (the provisioner already writes it) and `CANARY_REBALANCER_ENABLED=false`: its frame
asks it to refill its own senders, so it needs no rebalancer of its own.

A kit frame's compose maps the first six from their `FT_REG_` names, which is why they carry that prefix and the rest
do not. On any registry whose compose does not map them (a cloud operator, for instance), write the plain names. A
value written in the compose `environment:` block always beats the env file, and a value in the env file beats the
network profile's.

### 9. Watch the first cycle

```bash
docker logs --since 5m <registry> | grep -E "CanaryRunner|CanaryJudge|CanaryRebalancer"
curl -s -H "Authorization: Bearer $ADMIN_JWT" "$REG/api/v1/admin/canary/status" | jq '.summary'
curl -s -H "Authorization: Bearer $ADMIN_JWT" "$REG/api/v1/admin/canary/fleet/status" | jq '{mode, fleet_paused}'
```

You want `FIRED`/`DISPATCH` lines, `cycle done: fired=N errors=0`, the judge's `→ passed`, and your supply delta still
`0.0`. The dashboard is at `#/admin/canaries` in the console (the platform admin flag).

## What it costs, and how to keep it from draining your frame

Every fire moves units, and on a frame with a small supply a careless matrix bleeds the treasury into agents that
never spend. Two rules keep it flat:

1. **Make the units circulate.** A cross-registry path pays the far registry's **sender**, and a local path runs both
   ways (`-local` and `-local-back`). Then every canary agent both sends and receives, each pair nets out, and only
   fees leave the loop. Pay a dedicated receiver on every leg instead, and that receiver grows forever: the rebalancer
   only looks after agents that send.
2. **Let the rebalancer hold a band.** Once a day is plenty. Below `CANARY_REBALANCER_FLOOR_AVT` it tops an agent up by
   `CANARY_REBALANCER_TOPUP_AVT` from its own registry's treasury (at most once an hour per agent); above
   `CANARY_REBALANCER_CEILING_AVT` it returns everything beyond floor plus top-up to that treasury (free of fees,
   supply neutral, at most one sweep per agent per day). `CANARY_REBALANCER_CEILING_AVT=0`, the default, means it only
   ever pays out.

Sizing: make the floor cover more than one day of an agent's worst case, which is every outgoing path firing while
every incoming one fails: `outgoing paths × 86400 / interval × amount`. Put the ceiling well above floor plus top-up:
a ceiling at or below it turns the sweep off, because a sweep there would leave an agent where the next refill pays it
again. At 0.1 a fire every 1800 s, 25 / 25 / 150 is comfortable; at 1.0 a fire, 200 / 300 / 2000.

A developer's first agent receives the genesis grant where the registry gives one, so `svc-canary`'s first canary
usually starts far above the band. The first sweep returns that grant to the treasury, which is the point: it belongs
there, not parked in a monitor.

## Traps worth knowing

- **The pause flag is per registry.** `POST /api/v1/admin/canary/fleet/pause` sets a key in **that** registry's own
  Redis, and it stays until a resume clears it. A stale pause on an operator makes its refill answer `paused` while
  dispatched fires still execute, which looks like a rebalancer that does not work. Ask `fleet/status` on every node,
  not just the frame.
- **A maintenance call without a scope touches every path.** `POST /api/v1/admin/canary/maintenance` takes `scope`
  `"all"` when the body names none, so `{"enable": false}` switches off every path on that node. A list limits it to
  those paths' numeric row ids (`canary_paths.id`, not the `path_id` names), and an empty list touches nothing.
- **`POST /api/v1/admin/canary/fire` talks to a scheduler.** On a follower it fires nothing: an operator's paths fire
  when its frame dispatches them, on the frame's schedule.
- **Canaries are dark by design.** If one shows up in discovery, its owner lost `agents_unlisted_by_default`; fix the
  developer rather than the agent.

See also: [Monitoring & Observability](/docs/16) for health, metrics and the canary reactor, and
[Units and Fees](/docs/02) for what the transfers cost in fees.
