"""Who counts as a developer of THIS registry (§NIGHTLYTRUTH-2, 2026-10-11).

A row that is not soft-deleted and is not a federation placeholder. `is_federation_shadow` rows are the FK plumbing a
federated agent card needs (`agent_cards.developer_id` is NOT NULL), created by the sync for every peer developer whose
cards arrive, carrying a synthetic address under `<peer>.federation`: never a person. The admin developer list hides
both by default (`include_deleted`, `include_federated`), while the dashboard, the registry card's stats block and a
frame-wide broadcast's recipients and reach counted them: measured on sandbox-A 2026-10-11, the list held 1,324
developers, the dashboard said 1,450 (126 placeholders from sandbox-B, made on 10-10 as its test accounts' cards
federated), the card said 2,163 (also 711 accounts the tester's lifecycles had deleted), and a broadcast email would
have gone to all 2,163, the deleted ones' kept addresses included. One predicate for every count and recipient list, so
no two surfaces mean different people by "developers"; the admin list keeps its own switches for showing the rest.
"""
from sqlalchemy import and_

from agentvault_registry import models


def a_developer_of_this_registry():
    """The SQL predicate: not soft-deleted, not a federation placeholder."""
    return and_(models.Developer.deleted_at.is_(None), models.Developer.is_federation_shadow.is_(False))
