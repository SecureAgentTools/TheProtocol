<!-- GENERATED from AgentVault/agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src/assets/docs/operator/20_test_verified_development.md by scripts/distribution/gen_public_docs.py. Edit that file, not this copy: the export refuses a copy that differs from its source. -->

# Test-verified development

A change to the kit is suggested together with the evidence that it breaks nothing the release passed: the same test
suite, run in a sandbox on the release and again on your build, and the comparison of the two runs. Every command below
runs from `scripts/distribution/` in the kit you unpacked, as root on the host that runs your frame. Five scripts there
carry the loop, and the ones that handle evidence refuse, with a sentence, when it would not be about your change.

| Script | What it does |
|---|---|
| `frame-sandbox.py` | stands a sandbox up beside your frame, the way the kit stands any frame up |
| `frame-test.py` | runs the MCP tester's suite inside the sandbox: a baseline on the release, then a comparison |
| `build.sh` | builds the kit's images from your tree, under a version name of yours |
| `frame-update.py` | puts your build on the sandbox, and takes it back off |
| `frame-contribute.py` | packs the patch and the evidence into one archive |

## What you need

- **A frame on this host, stood up with `frame-up.py --with-runner`.** If you don't run one yet, stand it up first,
  following the README's "Run a federated frame on your own host". The frame runner does the host work for a sandbox.
  Its policy allows sandboxes unless it was installed with `--no-sandboxes`.
- **The frame's wildcard DNS record, `*.<public name>`, pointing at this host.** The same record serves the frame's cloud
  operators.
- **Memory.** A sandbox uses about 2.5 GiB, or 3.5 GiB with its cloud operator. Two federated sandboxes use about
  5.1 GiB, or 7.0 GiB with an operator on each (the figures the Sandbox panel shows). The sandboxes are stood up one
  after another, and each standup checks for 8 GiB free when it starts, the floor `frame-doctor.py` (the kit's
  preflight) sets for any frame, along with 20 GB of free disk and the host's load. If one of them is short, the
  refusal names it.
- **The kit you downloaded, unpacked, and the tarball itself.** Its `KIT_FILES.sha256` lists the digest of every file
  in the release. That list is how a build tells your change apart from the release. Keep the tarball: frame-contribute
  takes the original files from it.

**Names.** A sandbox is named after its frame: `<frame>sbx`, and `<frame>sbxb` for the second one of a pair. Their
consoles answer as `sandbox.<public name>` and `sandbox-b.<public name>`, and their cloud operators as
`<frame>sbxop.<public name>` and `<frame>sbxbop.<public name>`. The examples below use a frame named `myframe`, so its
sandbox is `myframesbx`.

**Where things go.** `<stack-root>` is the directory frame-up put your frame's stack in: its `--stack-root`, which is
`/opt/theprotocol/stack` unless you chose another. The sandboxes' stacks go beside your frame's, and the test reports
go to `<stack-root>/<sandbox>-tests/`.

## 1. Stand the sandbox up

**In the console.** Log in to your frame as its admin and open the MCP tester (`#/admin/mcp-tester`). On a production
frame the tester never runs against the frame itself. Its Sandbox panel offers two choices:

- **One frame** runs the lifecycle sweep, which calls every MCP tool the sandbox serves, public and admin.
- **Two federated frames** adds the federation suite, a separate run of several hundred checks across both frames and
  their operators. Tick **A cloud operator on each frame** as well, because the federation suite needs them.

**Provision** lists each step as it runs. If a step fails, the panel names it and says why. **Try again** picks up where
it stopped, skipping the steps that already stand. When the sandbox is ready, the panel links its console, its MCP
tester and its admin login.

**On the command line:**

```bash
cd scripts/distribution
./frame-sandbox.py up --for myframe                            # one sandbox: myframesbx at sandbox.frame.example.org
./frame-sandbox.py up --for myframe --frames 2 --operators     # two federated sandboxes, an operator each
./frame-sandbox.py status --for myframe
```

If `up` stops at a step, run it again after fixing what it named: it skips the steps that already stand.

A sandbox is stood up through the same lanes as any real frame:

- frame-up stands up each sandbox.
- The invitation rail federates the two sandboxes.
- Each operator goes through the application, the approval, the activation and the provisioning.

So a test that passes in the sandbox has passed through the doors a real frame has. Every write a test makes lands in
the sandbox. The sandbox shares nothing with your frame except the host, the edge and the frame runner.

## 2. Take the baseline

Run the suite on the release images, before you change anything:

```bash
./frame-test.py --name myframesbx --baseline
```

This runs the lifecycle sweep (the flow `flow_mcp_lifecycle_complete`, the default) inside the sandbox, against the
sandbox itself. When it finishes it prints the report's path, `<stack-root>/myframesbx-tests/<time>-<flow>.json`, and
copies it to `baseline-<flow>.json` in the same directory.

On a pair, both suites run in the first sandbox, `myframesbx`. Take a baseline of each flow:

```bash
./frame-test.py --name myframesbx --baseline
./frame-test.py --name myframesbx --baseline --flow flow_federation_suite_complete
```

A report records what was measured:

- the verdict for every tool (pass, fail or skip), and the reason for each one that did not pass
- the build the sandbox ran, read from its `/health`: the kit version, the digest of the source tree, and whether that
  tree differs from the release
- the registry image's id and labels
- a hash of the suite's own files

frame-test refuses to take a baseline on a build that differs from the release. The release's own reds are part of the
baseline. When the comparison later lists them as "still red", they don't count against your change.

## 3. Change, build, and put the build on the sandbox

Edit the kit tree you unpacked, then build it under a version name of your own:

```bash
./build.sh --version 1.0.0-mine.1
#   prints the provenance (the tree's digest, modified=true and how many files differ from the release; dist/build-info.json
#   names up to 20 of them); every image carries it in its labels, and the registry shows it at /health
./frame-update.py --name myframesbx --version 1.0.0-mine.1
```

A changed tree's images take only your version tag. `:latest` and `:stable` stay on the release, so a restart of
anything that runs `:stable` never picks up your experiment.

frame-update recreates only the services whose image changes, the ledger first and the registry last. Volumes, data
and secrets stay, and the registry runs its migrations at boot. It then reads `/health`, and the ledger's supply delta
before and after, which must stay 0.0 (it exits 6 otherwise).

frame-update refuses a local build on any frame whose posture is not sandbox. On a pair, update both sandboxes
(`--name myframesbx` and `--name myframesbxb`). The sandboxes' cloud operators keep the images they were provisioned
with, because frame-update does not reach them.

## 3b. The control run (only when your change touches the tests)

A change to the test suite (anything under `api_tests/`) cannot be judged by comparing two runs: the release ran the
old suite and your build runs the new one. It needs a third run in between, the control: your new suite on the
unmodified release. Make the suite change first, on its own, and nothing else:

```bash
./build.sh --version 1.0.0-mine.control          # the release plus your suite change, nothing else
./frame-update.py --name myframesbx --version 1.0.0-mine.control
./frame-test.py --name myframesbx --run          # prints the report's path: keep it, this is the control
```

Then make the code change, build it under your version and put it on the sandbox as in step 3, and run the suite once
more with `./frame-test.py --name myframesbx --run`: that is the after report. (`--compare` would refuse it, because the
baseline ran another suite.) On a pair, take a control for each flow.

What the three runs must show, and what `frame-contribute.py` checks before it packs them (section 3b of
`REVIEWING.md`):

- the control turns no test red that passed on the release;
- the tests you added may fail in the control: they are your change's own tests, failing before the change exists;
- the after report holds no new red against the control, and every one of those failing tests passes.

## 4. Compare

```bash
./frame-test.py --name myframesbx --compare
./frame-test.py --name myframesbx --compare --flow flow_federation_suite_complete     # on a pair, as well
```

Each command runs the suite again, prints the new report's path, and compares the result with that flow's baseline.
The exit code gives the verdict:

| Exit | Meaning | What to do |
|---|---|---|
| 0 | No new red. New greens are listed. | Package it (step 5). |
| 1 | New reds, each named with the reason the tester gave. | Fix them, then build, update and compare again. |
| 2 | Refused before comparing; the sentence says why (no such sandbox, no baseline for that flow yet, the sandbox's admin cannot log in, ...). | Do what the sentence names. |
| 3 | The run did not finish within `--timeout-min` (60 minutes). | Read the sandbox's MCP tester view for where it stalled. |
| 4 | Not comparable: the two runs did not measure the same thing. | See below. |

A changed test is not evidence about the code, so a changed suite makes the runs not comparable. Exit 4 means the
suite's own files differ between the two runs, the reports ran different flows or were written in different formats,
or your build changes a different release from the one the baseline ran. Either your change touched the test suite
itself, which needs the control run of step 3b and `--run` instead of `--compare`, or the sandbox moved to a different
release since the baseline; then roll back (below) and take the baseline again.

To try another build, or when you are done, put the previous images back:

```bash
./frame-update.py --name myframesbx --rollback
```

A rollback undoes the last update only (frame-update records each one in the sandbox's `frame-update.json`): after
several updates, run it once per update to reach the release images.

## 5. Package the suggestion

```bash
./frame-contribute.py --pristine /path/to/the-kit-you-downloaded.tar.gz \
    --baseline <stack-root>/myframesbx-tests/baseline-flow_mcp_lifecycle_complete.json \
    --after    <stack-root>/myframesbx-tests/<time>-flow_mcp_lifecycle_complete.json \
    --signoff  "Your Name <you@example.org>"
#   writes dist/contribution-<time>.tar.gz at the root of the kit you unpacked
```

The `--after` report is the one your last `--compare` printed. On a pair, give one `--baseline` and one `--after` per
flow; they are paired in the order you give them:

```bash
./frame-contribute.py --pristine /path/to/the-kit-you-downloaded.tar.gz \
    --baseline <stack-root>/myframesbx-tests/baseline-flow_mcp_lifecycle_complete.json \
    --after    <stack-root>/myframesbx-tests/<time>-flow_mcp_lifecycle_complete.json \
    --baseline <stack-root>/myframesbx-tests/baseline-flow_federation_suite_complete.json \
    --after    <stack-root>/myframesbx-tests/<time>-flow_federation_suite_complete.json \
    --signoff  "Your Name <you@example.org>"
```

When your change touches the tests, give each flow's control report as well (`--control`, once per flow, in the same
order); frame-contribute refuses a suite change without one, and a control without a suite change:

```bash
./frame-contribute.py --pristine /path/to/the-kit-you-downloaded.tar.gz \
    --baseline <stack-root>/myframesbx-tests/baseline-flow_mcp_lifecycle_complete.json \
    --control  <stack-root>/myframesbx-tests/<time of the control run>-flow_mcp_lifecycle_complete.json \
    --after    <stack-root>/myframesbx-tests/<time of the after run>-flow_mcp_lifecycle_complete.json \
    --signoff  "Your Name <you@example.org>"
#   the header's tests line then reads "<flow> <baseline> -> <control> -> <after>, red then green: N"
```

The archive holds:

- **the patch**: a unified diff of every file your tree changed against the release. `KIT_FILES.sha256` names the
  changed files, and the tarball supplies the originals. The patch starts with the kit version, both tree digests,
  each flow's result and your `Signed-off-by` line (the Developer Certificate of Origin, `DCO.md` at the root of the
  kit).
- **each flow's two reports and their comparison**, and each flow's control report when your change touches the tests
- **a manifest** with the sha256 of each file in the archive

frame-contribute refuses to package evidence that is not about this change. For every flow, each of these must hold:

- The after report measured this exact tree. If you edited anything after the run, build, update and compare again.
- The baseline ran the unmodified release.
- Both reports ran the same suite, or, when your change touches the tests, each flow brings its control (step 3b)
  and the three runs show red then green.
- The after report holds no new red.

Attach the archive to the pull request or issue that proposes the change: `CONTRIBUTING.md` at the root of the kit
says where it goes, and `REVIEWING.md` what happens next. The maintainer runs `frame-review.py` over the archive, which
recomputes every claim it makes and answers with one page of verdicts, and then reads the diff. You can run the same
check yourself before you send:

```bash
./frame-review.py dist/contribution-<time>.tar.gz --pristine /path/to/the-kit-you-downloaded.tar.gz
#   REFUSED names what to fix; HELD names what it waits for (your CLA acceptance is on the maintainer's file, so R8 is
#   HELD when you run it yourself); MERGEABLE means the evidence holds and the reading can start
```

## 6. Tear the sandbox down

In the console, use **Tear down** in the Sandbox panel. On the command line, run
`./frame-sandbox.py down --for myframe`. This removes the operators through their frames' own admin API, then each
sandbox with `frame-down.py` (the kit's teardown, the counterpart of frame-up). The reports stay in
`<stack-root>/<sandbox>-tests/`.

## The checks every pull request runs

The repository's own workflow (`.github/workflows/ci.yml`) runs on every pull request, with no secret and no frame:

- the registry and the TEG: a compile gate, an undefined-name gate (pyflakes, zero allowed), the source contract
  checks and the migration graph;
- the event store: the supply-invariant tests, and its issuance-origin and authentication tests;
- the Directory's reader tests, the kit tools' own tests (`scripts/distribution/tests`) and the auditor's tests;
- the SDK's suite, on Python 3.10 and 3.14.

Each suite has a floor and a skip ceiling, so a suite that stops running fails instead of passing. Each job's commands
are in that file: run them locally before you push. What needs a frame (the image builds and the MCP tester's runs) is
the sandbox loop on this page.

## What the evidence says, and what it doesn't

- **What it says:** the suite the release passed still passes on your build, in a frame stood up the way the kit stands
  frames up. It doesn't say the change is right. Review is still review.
- **What each suite covers:** the lifecycle sweep covers the MCP tools one frame serves. The federation suite covers what
  crosses between two frames and their operators. A change to federation needs the pair.
- **What it can't verify:** a change to the instruments themselves (`frame-test.py`, `frame-contribute.py`,
  `frame-review.py`, `kit_provenance.py`, the MCP tester's router). A change to the suite is verified by its control
  run (step 3b): the new tests fail on the release and pass on your change.
