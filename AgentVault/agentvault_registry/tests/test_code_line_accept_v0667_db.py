"""V0667 follow-up (order gwo_33f89c6c8086e9626d1a0b93; found by session-release's D6 sandbox dry run, room seq 5747): a LINE's change is accepted on a record that reads
it against the LINE's own branch, through the real store on a real Postgres.

The defect: `record_acceptance` compared the checker's `base` with the PLATFORM release branches (CODE_CHANGES_RELEASE_BRANCHES, `main` on production) for every change, but a
line's change is built on the line's own branch (distribution/<release>_<line>) and its merge goes into that branch (`record_merge` already knew). The checker read Lyceum's change
cleanly against its own line (ci success, 1 path, 0 secrets) and the registry refused it with 409 base: on production no line's change could be accepted.

  a line's change   accepted on a record against its own line's branch; refused 409 base on a record against a platform release branch or another line's branch,
                    the refusal naming the branch it expected
  a platform change keeps today's rule: accepted against a release branch; refused against a line's branch

Runs where CODE_CHANGES_TEST_DB names a throwaway database (its name starting with test_); skipped, saying why, elsewhere.
"""
from __future__ import annotations

import os
import uuid

import pytest

if not os.environ.get("CODE_CHANGES_TEST_DB"):               # this file's own skip: importing the bootstrap test below would raise ITS skip, and CI counts skips by the file that raised them
    pytest.skip("needs a REAL Postgres it may wipe: set CODE_CHANGES_TEST_DB (a database whose name starts with test_). Skipped, never silently passed.", allow_module_level=True)

from agentvault_registry.services import code_changes as cc  # noqa: E402
from tests.test_code_changes_bootstrap_hold_pg_v0666 import ADMIN, db, _now, _stamp  # noqa: E402,F401  (db is the fixture)
from tests.test_code_changes_flow_v0663 import (   # noqa: E402,F401  (the autouse fixture sets the maintainer, the release line, the key and the governing registry)
    CHECK_SCHEMA, CONSOLE, REPO, SHA, _maintainer_and_release_line, sign_record)

PATH = CONSOLE + "assets/docs/oracle/37_proxy.md"


async def _changes(db, monkeypatch):
    """A line `lyceum` on V0667 (open path: the docs), another line `delta`, a change of the first line and a change of the main line, both proposed as branches."""
    from agentvault_registry import models
    monkeypatch.setenv("CODE_DISTRIBUTIONS_ENABLED", "true")
    org = models.Organization(id=f"org-{uuid.uuid4().hex[:8]}", name="Lyceum", slug=f"lyceum-{uuid.uuid4().hex[:6]}", owner_id=1)
    db.add(org)
    await db.flush()
    lines, tag = {}, uuid.uuid4().hex[:6]
    for key, slug in ("own", f"lyceum{tag}"), ("other", f"delta{tag}"):          # a slug is unique across the registry
        row = models.CodeDistribution(id=f"cdst_{uuid.uuid4().hex[:12]}", organization_id=org.id, slug=slug, title=slug, base_release="V0667", open_paths=[CONSOLE + "assets/docs/"],
                                      decider_team_id=None, quorum_percent=50, pass_rule="simple", state="active", created_by_developer_id=1)
        db.add(row)
        lines[key] = row
    await db.flush()
    out = {"own": f"distribution/V0667_{lines['own'].slug}", "other": f"distribution/V0667_{lines['other'].slug}", "older": f"distribution/V0666_{lines['own'].slug}"}
    for key, dist in (("line", lines["own"]), ("platform", None)):
        cid = f"cc_{uuid.uuid4().hex[:20]}"
        db.add(models.CodeChange(id=cid, repository=REPO, paths=[PATH], title=f"{key} docs change", problem="One sentence in the docs.", mode="branch", branch=f"{key}/docs",
                                 commit=SHA, proposer_did="did:a:proposer", proposer_developer_id=1, sensitive=False, state="proposed",
                                 code_distribution_id=dist.id if dist else None))
        out[key] = cid
    await db.commit()
    return out


def _record(cid, base, minutes_ago=5):
    import datetime as dt
    return sign_record({"schema": CHECK_SCHEMA, "kind": "acceptance", "repository": REPO, "change_id": cid, "commit": SHA, "issued_at": _stamp(_now() - dt.timedelta(minutes=minutes_ago)),
                        "ci_state": "success", "base": base, "touched": [PATH], "secret_findings": 0, "secret_paths": [], "too_many_touched": False})


async def _accept(db, cid, base):
    flow = cc.CodeChangeFlow(cc.DbStore(db))
    return await flow.record_acceptance(ADMIN, cid, {"signed": _record(cid, base)})


async def test_a_lines_change_is_accepted_on_a_record_against_its_own_lines_branch(db, monkeypatch):
    ids = await _changes(db, monkeypatch)
    out = await _accept(db, ids["line"], ids["own"])
    assert out["state"] == "accepted"
    assert out["acceptance"]["record"]["base"] == ids["own"], out["acceptance"]


@pytest.mark.parametrize("which", ["main", "v0663/cut", "other", "older"])
async def test_a_lines_change_is_refused_on_a_record_against_the_platforms_branch_or_another_lines(db, monkeypatch, which):
    ids = await _changes(db, monkeypatch)
    with pytest.raises(cc.CodeChangeRefusal) as e:
        await _accept(db, ids["line"], ids.get(which, which))
    assert e.value.status == 409 and e.value.code == "base"
    assert ids["own"] in e.value.sentence, "the refusal names the branch it expected"


async def test_a_platform_change_keeps_todays_rule(db, monkeypatch):
    ids = await _changes(db, monkeypatch)
    assert (await _accept(db, ids["platform"], "v0663/cut"))["state"] == "accepted"
    ids2 = await _changes(db, monkeypatch)
    with pytest.raises(cc.CodeChangeRefusal) as e:
        await _accept(db, ids2["platform"], ids2["own"])
    assert e.value.status == 409 and e.value.code == "base" and "v0663/cut" in e.value.sentence
