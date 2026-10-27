"""
BaseA2AAgent — Abstract base class for TheProtocol A2A agents.

Subclass this and implement the handle_* methods to create an agent.
"""

import logging
from typing import Optional, Dict, Any, AsyncGenerator

from ..models import Message, Task, A2AEvent

logger = logging.getLogger(__name__)


class BaseA2AAgent:
    """
    Abstract base class for A2A agents.

    Implement the four handle methods to define your agent's behavior:
    - handle_task_send: Process incoming messages
    - handle_task_get: Return current task state
    - handle_task_cancel: Cancel a running task
    - handle_subscribe_request: Stream SSE events for a task

    Example::

        class MyAgent(BaseA2AAgent):
            async def handle_task_send(self, task_id, message):
                # Process the message and return task ID
                return "task-123"

            async def handle_task_get(self, task_id):
                # Return the current task state
                return Task(id=task_id, state=TaskState.COMPLETED, ...)

            async def handle_task_cancel(self, task_id):
                return True

            async def handle_subscribe_request(self, task_id):
                yield TaskStatusUpdateEvent(...)
    """

    def __init__(self, agent_metadata: Optional[Dict[str, Any]] = None):
        self.agent_metadata = agent_metadata or {}
        logger.info(f"Initialized {self.__class__.__name__}")

    async def handle_task_send(self, task_id: Optional[str], message: Message) -> str:
        """Handle incoming message. Return task ID."""
        raise NotImplementedError("Implement handle_task_send")

    async def handle_task_get(self, task_id: str) -> Task:
        """Return current task state."""
        raise NotImplementedError("Implement handle_task_get")

    async def handle_task_cancel(self, task_id: str) -> bool:
        """Cancel a task. Return True if accepted."""
        raise NotImplementedError("Implement handle_task_cancel")

    async def handle_subscribe_request(self, task_id: str) -> AsyncGenerator[A2AEvent, None]:
        """Yield SSE events for a task."""
        raise NotImplementedError("Implement handle_subscribe_request")
        if False:  # pragma: no cover
            yield  # Make it a generator
