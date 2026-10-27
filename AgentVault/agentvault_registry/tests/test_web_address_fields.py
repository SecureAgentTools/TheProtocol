"""§FESUITE 135 (agentvault2-5b, 2026-10-15): the addresses others press as links are http(s) or nothing.

An organization's website and a developer's website and GitHub page are rendered as links in the console. The
registry stored any string, so a "javascript:" website became a link that ran in the console's origin for whoever
pressed it (spec 135 stored one through PUT /organizations/{id} and read it back). Refused where it is written now;
an empty value still clears the field, and None (not given) leaves it alone.
"""
import pytest
from pydantic import ValidationError

from agentvault_registry.core.web_address import web_address_or_empty
from agentvault_registry.routers.organizations import OrganizationCreate, OrganizationUpdate
from agentvault_registry.schemas import DeveloperProfileUpdate

REFUSED = [
    "javascript:alert(document.domain)",
    "  JavaScript:alert(1)",
    "data:text/html,<b>x</b>",
    "vbscript:msgbox(1)",
    "ftp://files.example.org/x",
    "//evil.example/x",
    "example.org",
    "https://exa mple.org",
]
ACCEPTED = ["https://example.org", "http://example.org/path?q=1", "HTTPS://Example.org/x"]


@pytest.mark.parametrize("bad", REFUSED)
def test_the_helper_refuses_anything_but_http(bad):
    with pytest.raises(ValueError, match="http:// or https://"):
        web_address_or_empty(bad, "website")


@pytest.mark.parametrize("good", ACCEPTED)
def test_the_helper_keeps_an_http_address(good):
    assert web_address_or_empty(f"  {good} ") == good


def test_empty_clears_and_none_leaves():
    assert web_address_or_empty("") == ""
    assert web_address_or_empty("   ") == ""
    assert web_address_or_empty(None) is None


@pytest.mark.parametrize("bad", REFUSED)
def test_an_organization_refuses_the_website(bad):
    with pytest.raises(ValidationError):
        OrganizationCreate(name="abc org", website=bad)
    with pytest.raises(ValidationError):
        OrganizationUpdate(website=bad)


def test_an_organization_keeps_an_http_website_and_clears_an_empty_one():
    assert OrganizationCreate(name="abc org", website="https://example.org").website == "https://example.org"
    assert OrganizationUpdate(website="").website == ""
    assert OrganizationUpdate().website is None


@pytest.mark.parametrize("field", ["website_url", "github_url"])
@pytest.mark.parametrize("bad", REFUSED)
def test_a_profile_refuses_the_address(field, bad):
    with pytest.raises(ValidationError):
        DeveloperProfileUpdate(**{field: bad})


def test_a_profile_keeps_http_addresses():
    p = DeveloperProfileUpdate(website_url="https://example.org", github_url="https://github.com/someone")
    assert (p.website_url, p.github_url) == ("https://example.org", "https://github.com/someone")
    assert DeveloperProfileUpdate(website_url="").website_url == ""
