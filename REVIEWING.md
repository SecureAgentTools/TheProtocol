# How a suggested change is reviewed

This file is the other half of [`CONTRIBUTING.md`](CONTRIBUTING.md). That one says what you send; this one says what
happens to it, who does it, how long it takes, and what gets a change refused before anyone reads it. The project has
one maintainer today. The process is built so that one person can run it honestly, and so that you can see where your
suggestion stands without asking.

## 1. What review is here

Two things, in this order:

1. **Does the evidence hold?** You send a change with the proof that it breaks nothing the release passed: the MCP
   tester's suite run in a sandbox on the release and on your build, packed by `frame-contribute.py` ([test-verified
   development](PUBLIC_DOCS/TEST_VERIFIED_DEVELOPMENT.md)). The maintainer runs `scripts/distribution/frame-review.py`
   over that archive. It recomputes every claim the archive makes and writes one page of verdicts. That page is the
   first thing the maintainer reads and the first thing you get back.
2. **Is the change right?** A machine cannot answer that. The maintainer reads the diff against the issue it answers,
   against the invariant where value moves, and against the words a user will see.

The evidence never replaces the reading. It decides whether the reading starts.

## 2. Where suggestions go

- **A pull request** at <https://github.com/SecureAgentTools/TheProtocol>, with the `frame-contribute` archive
  attached to it and the CLA acceptance line from [`CLA.md`](CLA.md) in its description (or once, in an issue titled
  "CLA acceptance"), so the acceptance is on file before the review starts.
- **The archive by mail** to **r.jeziorny@theprotocol.cloud** when you cannot or do not want to open a pull request.
  The review is the same; the archive is what is reviewed, not the transport.
- **Security issues never go through either door.** Report them to **SecurityAlerts@theprotocol.cloud** as
  [`SECURITY.md`](SECURITY.md) says. A public pull request that fixes an undisclosed vulnerability is closed and
  redirected there.

## 3. What the machine checks

`frame-review.py` answers twelve questions, each GREEN, RED, HELD or NOT MEASURED, each with the sentence that says why:

| # | question |
|---|---|
| R1 | Is the archive the shape `frame-contribute` writes: one directory, the patch, the manifest, and per flow two reports plus a comparison, or three reports when the change touches the test suite (a control for every flow or for none)? |
| R2 | Does every file match its sha256 in the manifest? |
| R3 | Does the patch header name the kit version, both tree digests, the file count, every flow, and a `Signed-off-by` line with a real-looking name and address? |
| R4 | Per flow: did the baseline run the unmodified release the patch changes, did the after report measure exactly the changed tree, same suite, same report format, and is there **no new red**, recomputed from the reports, not read from the comparison? With a control, the rules of §3b, recomputed; an existing test gone from the suite is HELD, a human decides. |
| R5 | Is the diff reviewable: no binary file, no env file, no key, the file count as stated, within the size caps of §4; which areas does it touch (money, contracts, migration, identity, federation, frontend, kit, legal, the suite)? A suite change without its control is RED. A change to the instruments themselves (`frame-test`, `frame-contribute`, `frame-review`, `kit_provenance`, the MCP tester's router) is HELD, because the evidence cannot verify a change to the thing that produces it. |
| R6 | Does any added line carry a secret shape (a private key, an API key, a pull token, a licence key, a long hex secret)? The value is never printed. |
| R7 | With the release kit at hand: is the header's release tree that kit's tree, does the patch apply to it cleanly, and did every control run measure the release plus exactly the suite part of the patch? |
| R8 | Is your CLA acceptance on file? Not yet is HELD, never refused: the archive may be right and the record late. |
| R9 | When the maintainer reproduces the run on a sandbox: same suite, same tree, no new red (against the control when there is one), every new test green, the same verdicts. A differing verdict is HELD, a red the contributor did not see is RED. Not reproduced is NOT MEASURED and says so. |
| R10 | Does every `tests:` line in the header match the reports it names, in either form (two runs, or three with "red then green: N")? |
| R11 | Red then green: for a suite change, how many new tests failed on the release and pass on the change, per flow. A rule of §3b broken is RED; a test gone from the suite is HELD. Without a suite change: GREEN, two runs are the evidence. |
| R12 | Coverage: a change to money, contracts or federation brings the federation suite as well; for money and contracts every tool of the after report that names the supply, a delta, the invariant or solvency passes. A tool that does not is RED; a report with none is NOT MEASURED, and the invariant is read by hand. |

**REFUSED** on any RED. **HELD** on any HELD, waiting for the thing the row names. **MERGEABLE** otherwise, with the
NOT MEASURED rows listed as what the maintainer still owes before merging. The page is attached to your pull request or
mailed back, verdicts and sentences, so a refusal always says what to change.

## 3b. When your change touches the tests

A changed test is not evidence about the code: two runs of different suites cannot be compared. So a change that touches
the test suite (anything under `api_tests/`, the tree the suite hash covers) brings three runs per flow instead of two:

1. **The baseline**: the release suite on the release, as always.
2. **The control**: your new suite on the unmodified release. Build the suite change alone, put it on the sandbox, run.
3. **The after report**: your new suite on your whole change.

The rules, which `frame-contribute` enforces before it packs and `frame-review` recomputes after:

- The control turns **no existing test red**: a changed test that fails on the release is not evidence about the code.
- The tests you add may fail in the control. They are your change's own tests failing before the change exists: the
  expected reds.
- The after report holds **no new red** against the control, and **every expected red is green** in it.

Red then green, in one archive: the page counts them per flow. A test that disappears from the suite is not refused, it
waits for a human, because removing a test is a decision about what the project promises.

## 4. What the maintainer reads and does

**Design first, for the parts that carry weight.** A change to money, contracts, identity or federation, and any change
over the size caps, starts as a design issue that the maintainer agrees to before the code is written. The caps count
code files and changed lines, docs excluded: **20 files or 600 lines**, and **12 files or 400 lines** when money,
contracts, identity or federation is touched. Over the cap, a change is split into suggestions that each fit, or the
design issue names it as a whole: then it is built on a feature branch the issue names, read in slices as it lands, and
brings one evidence run for the whole branch. The review page names the issue (`frame-review.py --design-issue`), and
the cap stops holding it.


1. The review page. A REFUSED page goes back to you with its sentences the same day it is read; nothing else happens
   until the archive is right.
2. The diff, slowly where the page says so: value moving (the supply invariant, the existing transfer rails, never a
   parallel money path), a migration (its downgrade is part of the change), identity or authority (who may call what,
   before and after), anything a user reads (sentence case, no em dashes, translated where the console is).
3. **Reproduction** for every change that touches money, contracts, identity, federation or a migration, and for anything the
   maintainer doubts: a sandbox from the kit, your patch applied to the release tree, `./build.sh`, `./frame-update.py`
   onto the sandbox, `./frame-test.py --compare`, and the maintainer's own after report handed to `frame-review.py
   --own-after`. A docs-only or tests-only change skips this step; the page says which kind it is.
4. **Merge.** Your commit keeps you as author and keeps your `Signed-off-by` line; the maintainer adds his own. The
   change lands on the default branch, then rolls the way every change rolls here: the sandbox pair first, one
   production frame as the canary, the rest on a decision. A release that carries your change names you in its notes.

## 5. What a single maintainer can promise

- An acknowledgement within **seven days** of the pull request or mail, even if it is only "received, in the queue".
- The review page within **fourteen days** for a change whose archive is complete. Reading and reproduction take
  longer for money, contracts, identity and federation, and the acknowledgement says so.
- Held changes are not forgotten: a HELD page names what it waits for, and the maintainer re-runs it when that arrives.
- No silent closes. A change that will not be merged gets a sentence saying why.
- Security reports follow the times in [`SECURITY.md`](SECURITY.md), which are shorter.

These are the times one person can keep. When the project has more maintainers this file changes with them.

## 6. Refused without reading

- No `Signed-off-by` line, or a pseudonym where the DCO asks for a name.
- A change to the platform with no evidence archive, or an archive whose evidence is about another tree.
- A secret, a key, an env file or personal data of anyone in the diff.
- A binary file where a text change was possible; a generated bulk change (reformatting, mass renames) with no issue
  behind it; a dependency bump with no reason and no evidence.
- A suite change without its control (§3b): the new tests were never shown failing on the release, so their green
  says nothing.

## 7. After the merge

- Your name stays on the commit and in the release notes. Attribution is never rewritten.
- The CLA acceptance record (name or account, version, date) is kept by the maintainer as [`CLA.md`](CLA.md) describes,
  on the maintainer's own host, never in a repository.
- If a merged change turns out to break the invariant or a federation lane, it is rolled back first and discussed
  second, in the issue, with the measurement that showed it.
