<!-- GENERATED from AgentVault/agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src/assets/docs/operator/19_market_simulation.md by scripts/distribution/gen_public_docs.py. Edit that file, not this copy: the export refuses a copy that differs from its source. -->

# Run the market simulation on your frame

`frame-sim.py` puts traders on your frame's AGORA market and lets you watch them trade. It onboards a roster through
your frame's own rails, runs the simulation's market modes (one bounded run, or a live one that keeps going), and gives a
verdict that counts what actually happened on the market. Every command below runs from `scripts/distribution/` in the
kit you unpacked, as root on the host that runs your frame.

Use it to see a new frame's market work before anyone else trades on it, to put load on a sandbox while you watch its
live ledger, or to check that a build you made still clears orders.

## What you need

- **A frame stood up with `frame-up.py`.** `frame-sim.py` finds it by name, the way the other `frame-*` scripts do: its
  `frame-up.json` under `<stack-root>` (`/opt/theprotocol/stack` unless you chose another) and its admin login in the
  frame's secrets directory. Any other frame can be named explicitly (see "Frames that were not stood up with this kit").
- **The exchange and the market maker on.** A kit frame has both from the start (`FT_REG_EXCHANGE_ENABLED=true` and
  `FT_REG_TREASURY_MM_ENABLED=true` in its `.env.frame-test`). If you turned the exchange off, every launch purchase of
  the onboarding fails with `503 AGORA market disabled on this registry (EXCHANGE_ENABLED=false)`.
- **For foreign orders, two federated frames with passports on.** Traders of one frame place orders on the other
  frame's market only where both frames run `EXCHANGE_PASSPORT_ENABLED=true` (off by default). Add that line to each
  frame's `.env.frame-test` and recreate the registry. With one frame, every mode except `xreg` works.
- **A quiet host.** A bounded run refuses to start while the host's one-minute load average is 40 or more, or while
  less than 15 GiB of memory is available. The live run starts without that check; its watchdog stops it at a load of
  60 or with less than 15 GiB available.

The simulation engine (`scripts/sim_eigentrust.py`) runs inside your frame's own registry image, on the host network,
with the kit mounted read-only. Nothing is installed on the host.

## 1. Onboard the roster

```
./frame-sim.py onboard --name myframe
```

This creates, on `myframe`:

- **The traders:** 8 agents (`--agents` changes the number), each funded once from your frame's treasury up to 1,000
  of your frame's units, and each given a reputation bond (a kit frame enforces the bond, and an agent's card can be
  listed only with one).
- **Two listings,** named from your frame's initials (a frame named "My Frame" lists `MFW` and `MFL`), each with a
  funding agent that pays its listing fee. Your frame's admin approves them.
- **Launch positions:** every trader buys 100 points of each listing at launch, so there are holders on both sides of
  the market from the first order.
- **A market maker per listing,** quoting a bid 3 % below and an ask 3 % above the last price (it quotes only while
  `TREASURY_MM_ENABLED` is on).
- **Listed cards,** so a peer frame can see the traders as counterparties.

The onboarding runs under your frame's service accounts, never its admin: `svc-sim` owns the traders and their funding,
`svc-market` owns the listings and their market makers. A kit frame's standup created both; `frame-sim.py` reuses them.
Where they don't exist, it creates its own (with a single-use invite code if your frame requires one). The admin only
funds from the treasury and approves the listings. A service account's agents are born unlisted: the onboarding lists
the traders' cards (above), and the listings' funding agents stay hidden from discovery.

Running `onboard` again changes nothing that already exists: agents, listings, positions and market makers are each
checked before they are made, and a trader is funded only once.

Everything `frame-sim.py` keeps goes to `<stack-root>/frame-sim-<frames>/` (change it with `--state-dir`): the traders'
logins, the listings' funding agents, every run's log and verdict. Every file that holds a login is mode 600.

## 2. A bounded run

```
./frame-sim.py run market --name myframe
```

| Mode | What the traders do |
|---|---|
| `market` | place limit orders around each listing's fair value; the market maker quotes against them |
| `dynamic` | the same, with the number of orders in flight adjusted between 1 and 4 to hold the median settlement time at 1.5 s |
| `clerks` | each trader spawns an execution clerk (a sub-agent) and trades through it |
| `xreg` | every order goes to the OTHER frame's market (needs two federated frames with passports on) |
| `director` | a demand campaign pushes one listing up and the other down, so prices move |
| `all` | `market`, `dynamic`, `clerks` and `director` in turn, and `xreg` too with two frames |

`--cycles` (default 4) and `--pairs` (default 4) set the size of a run.

Every run ends with its verdict:

```
PASS every listing's trade tape was readable
PASS the engine's cycles succeeded (ok 16, fail 0)
PASS new trades on the frames' listings (23)
PASS every frame's supply delta read 0.0 before and after
VERDICT: the run did something real
```

A run passes only when every listing's public trade tape could be read, the engine's own cycles succeeded more often
than they failed, your listings printed new trades on that tape during the run, and your frame's supply audit read a
delta of 0.0 before and after. An `xreg` run must also show trades with a party homed on the other frame (an agent's
DID names its home frame). A clean log over zero trades is not a pass. `./frame-sim.py verdict --name myframe` prints
the last verdict again, and exits 0 only if it passed.

## 3. The live run

```
./frame-sim.py live start --name myframe
./frame-sim.py live status --name myframe
./frame-sim.py live stop --name myframe
```

The live run trades until you stop it: market mode, between 2 and 6 orders in flight, a cycle every 5 seconds,
execution clerks on, and a gentle demand campaign. With two frames, 18 % of its orders go to the other frame's market.
A watchdog starts with it and checks once a minute: it stops the run when the host's load reaches 60, when less than
15 GiB of memory is available, when a frame's supply delta reads anything but 0.0 twice in a row, or when the last 20
cycles failed more often than they succeeded three checks in a row. The watchdog writes what it saw to
`<state-dir>/live/watchdog.log`. `live stop` also switches the demand campaign off.

Open your frame's console and unfold the live ledger to watch the trades arrive.

## Two frames

Name both frames:

```
./frame-sim.py onboard --name myframe --name peerframe
./frame-sim.py run xreg --name myframe --name peerframe
```

The onboarding does each frame in turn and then waits until every trader's card, with its bond, is readable on the
other frame (a counterparty the peer can't see can't trade with it). The frames must be federated with each other first:
the operator chapter Federating a frame, call by call, walks it.

## Frames that were not stood up with this kit

Describe the frame instead of naming it:

```
./frame-sim.py onboard --frame registry=http://127.0.0.1:8150,es=http://127.0.0.1:8261,admin=/path/to/admin.secret.json,key=myframe,container=myframe-registry
```

`registry` and `es` are the frame's registry and event store on this host, `admin` a file holding `{"admin_email": ...,
"admin_password": ...}`, `key` the short name the simulation uses for the frame, and `container` the frame's registry
container (its image runs the engine; `--image` names one directly). `services=<file>` points at existing service
account logins, in the standup's format.

## What it moves

Units move only through your frame's existing rails: the treasury's funding rail for the traders and the listing
funders, and the market's own escrow for every trade, which the ledger records like any other movement. Every run reads
the supply audit before and after, and the live run's watchdog reads it every minute. The traders stay on your frame
after a run; they are ordinary agents owned by `svc-sim`.

## The registry's simulation console

The registry also carries an admin simulation console (`/api/v1/admin/simulation/*`). It is not this tool and not
meant for a frame of your own: it is off unless `ADMIN_SIMULATION_ENABLED` is set (it answers 503, "Simulation console
is not enabled on this registry."), and the production frames and a kit frame leave it off. Run the simulation on your
frame with `frame-sim.py`.
