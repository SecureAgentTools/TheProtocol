"""§DOCSFIX CB-424: the registry card PUT refuses a tag the card's schema refuses.

The card schema allows at most 20 tags of at most 48 characters each. The admin PUT (schemas.RegistryCardOperatorPut)
limited the list to 20 but not the items, so it stored a 49-character tag and every card served after it failed its own
schema. The provisioning form's mirror (ProvisionCardOverrides) takes the same limits.
"""
import pytest
from pydantic import ValidationError

from agentvault_registry import schemas
from agentvault_registry.routers.operator_self_service import ProvisionCardOverrides


@pytest.mark.parametrize("model", [schemas.RegistryCardOperatorPut, ProvisionCardOverrides])
def test_a_tag_longer_than_48_characters_is_refused(model):
    with pytest.raises(ValidationError):
        model(tags=["x" * 49])


@pytest.mark.parametrize("model", [schemas.RegistryCardOperatorPut, ProvisionCardOverrides])
def test_the_schema_limits_still_pass(model):
    assert model(tags=["x" * 48] * 20).tags == ["x" * 48] * 20
    with pytest.raises(ValidationError):
        model(tags=["t"] * 21)
