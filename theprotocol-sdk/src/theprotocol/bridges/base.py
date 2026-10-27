"""
BaseBridge — Abstract base class for protocol translation bridges.

A bridge translates between an external agent protocol (ACP, ADK, MCP, etc.)
and A2A. This enables agents built with any protocol to interoperate
through TheProtocol registry.

Two directions:
  - Inbound:  External protocol → A2A (external client calls our A2A agent)
  - Outbound: A2A → External protocol (our client calls an external agent)
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from ..models import Message, Task
from ..agent.base import BaseA2AAgent


class BaseBridge(ABC):
    """
    Abstract bridge for translating between an external protocol and A2A.

    Subclass this to add support for a new protocol (ACP, ADK, etc.).

    Example::

        class ACPBridge(BaseBridge):
            async def external_to_a2a(self, request):
                # Convert ACP message → A2A Message
                return Message(role="user", parts=[TextPart(content=request["text"])])

            async def a2a_to_external(self, task):
                # Convert A2A Task → ACP response
                return {"text": task.artifacts[0].content, "status": task.state.value}
    """

    protocol_name: str = "unknown"

    @abstractmethod
    async def external_to_a2a(self, request: Any) -> Message:
        """Convert an incoming external protocol request to an A2A Message."""
        ...

    @abstractmethod
    async def a2a_to_external(self, task: Task) -> Any:
        """Convert an A2A Task result to the external protocol response format."""
        ...

    @abstractmethod
    def create_external_router(self, agent: BaseA2AAgent) -> Any:
        """
        Create protocol-specific HTTP routes that proxy requests to the A2A agent.

        Returns a FastAPI APIRouter (or similar) that handles the external
        protocol's endpoint format and translates to/from A2A internally.
        """
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} protocol={self.protocol_name}>"
