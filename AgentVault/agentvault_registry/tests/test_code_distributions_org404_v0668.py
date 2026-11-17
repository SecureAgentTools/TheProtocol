"""An organization's release lines (GET /api/v1/organizations/{org_id}/code-distributions): a missing organization answers 404 for
everyone, the platform admin included (order gwo_a0f717a778ac12962f88773f; V0667's pair proof nt261117x1 found a platform admin
naming a missing organization answered 200 with an empty list, because the admin skips the membership check and nothing then asked
whether the organization exists). An existing organization still lists for its members and for the platform admin.

The class, read on V0667's cut (every route of a line with an admin bypass, does its subject exist before the bypass applies):
code_distributions read, update, pause and resume look the line up first (404 not_found); create asks organization() before its
role check; content_changes view, vote, withdraw and undo load the change first; the content-change inbox's organization_id is a
filter, not the route's subject (an empty list is its answer); code_changes open_ballot and withdraw load the change first; D7's
report and record look the line up first; distribution_releases read and record look the name or the line up first. Only
list_for_org asked nothing.
The route on a real Postgres: test_code_distributions_org404_v0668_db.py.
"""
from __future__ import annotations

import pytest

from agentvault_registry.services import code_changes as cc
from agentvault_registry.services import code_distributions as cd
from tests.test_code_distributions_v0666 import ADMIN, ORG, LineStore, _line, run


@pytest.fixture(autouse=True)
def _lines_on(monkeypatch):
    monkeypatch.setenv("CODE_DISTRIBUTIONS_ENABLED", "true")


def _refused(coro):
    with pytest.raises(cc.CodeChangeRefusal) as e:
        run(coro)
    return e.value.status, e.value.code


def test_a_missing_organization_is_404_for_the_platform_admin_too():
    s = LineStore()
    _line(s)
    f = cd.CodeDistributionFlow(s)
    assert _refused(f.list_for_org(ADMIN, "org-missing")) == (404, "no_organization")
    assert _refused(f.list_for_org(ADMIN, "")) == (404, "no_organization")


def test_a_missing_organization_is_404_for_everyone_else_as_before():
    s = LineStore()
    f = cd.CodeDistributionFlow(s)
    for dev in (2, 8, None):
        assert _refused(f.list_for_org({"developer_id": dev}, "org-missing")) == (404, "no_organization")


def test_an_existing_organization_still_lists_for_its_members_and_the_platform_admin():
    s = LineStore()
    _line(s)
    f = cd.CodeDistributionFlow(s)
    for actor in ({"developer_id": 2}, {"developer_id": 7}, ADMIN):
        assert [d["slug"] for d in run(f.list_for_org(actor, ORG))["items"]] == ["lyceum"], actor
    assert _refused(f.list_for_org({"developer_id": 8}, ORG)) == (404, "no_organization")   # an outsider, as before
