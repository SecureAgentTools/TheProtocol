"""Build A2A-compliant agents."""

from .base import BaseA2AAgent
from .task_store import BaseTaskStore, InMemoryTaskStore, TaskContext
from .decorators import a2a_method

__all__ = [
    "BaseA2AAgent", "BaseTaskStore", "InMemoryTaskStore", "TaskContext",
    "a2a_method",
]

# Import router factory only if fastapi is available
try:
    from .router import create_a2a_router
    __all__.append("create_a2a_router")
except ImportError:
    pass

# A2A v1.0 §4.1.2 well-known discovery — also requires fastapi.
try:
    from .well_known import serve_well_known_card
    __all__.append("serve_well_known_card")
except ImportError:
    pass
