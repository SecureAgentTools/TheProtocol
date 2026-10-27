"""
Defines the base class for creating AgentVault A2A compliant agents.
"""

import logging
from dataclasses import dataclass, field
from typing import AsyncGenerator, Callable, Awaitable, List, Optional, Dict, Any, Union # Added Union

# Import core types from the agentvault library
try:
    from agentvault.models import Message, Task, TaskState
    # Import the Union type for events if defined, otherwise import individual events
    try:
        from agentvault.models import A2AEvent
    except ImportError:
        from agentvault.models import TaskStatusUpdateEvent, TaskMessageEvent, TaskArtifactUpdateEvent
        A2AEvent = Union[TaskStatusUpdateEvent, TaskMessageEvent, TaskArtifactUpdateEvent] # type: ignore

    _agentvault_models_imported = True
except ImportError as e:
    logging.getLogger(__name__).error(f"Failed to import core models from 'agentvault': {e}. SDK functionality will be limited.")
    # Define placeholders if import fails to allow basic SDK structure
    class Message: pass # type: ignore
    class Task: pass # type: ignore
    class TaskState: pass # type: ignore
    A2AEvent = Any # type: ignore
    _agentvault_models_imported = False


logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Attestation Schedule
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AttestationScheduleEntry:
    """
    Describes how and when an agent should self-attest for a given circuit.

    Used by the SDK integration layer to wire up ZKPAttestationClient triggers.

    Fields:
        circuit_id:        One of the known circuit IDs
                           (e.g. 'fairMarkupPolicy/v1.0.0').
        mode:              'periodic', 'event_driven', or 'both'.
                           - 'periodic':     start_periodic_attestation() is called
                             automatically with interval_seconds.
                           - 'event_driven': attest() is called by the agent after
                             each relevant transaction (manual trigger).
                           - 'both':         both mechanisms are active.
        interval_seconds:  Required when mode is 'periodic' or 'both'.
                           Sourced from RegistryEnforcementPolicy — governance can
                           vote to change this value.
        get_inputs_fn:     Async callable that returns the proof inputs dict
                           {'public_inputs': {...}, 'private_inputs': {...}}
                           or None to skip a periodic cycle.
                           Required when mode is 'periodic' or 'both'.
        event_types:       List of event type strings that trigger an event-driven
                           attestation (informational — agent implements the logic).
    """
    circuit_id: str
    mode: str  # 'periodic' | 'event_driven' | 'both'
    interval_seconds: Optional[float] = None
    get_inputs_fn: Optional[Callable[[], Awaitable[Optional[Dict[str, Any]]]]] = None
    event_types: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        valid_modes = {"periodic", "event_driven", "both"}
        if self.mode not in valid_modes:
            raise ValueError(f"AttestationScheduleEntry.mode must be one of {valid_modes}, got '{self.mode}'")
        if self.mode in ("periodic", "both") and self.interval_seconds is None:
            raise ValueError("interval_seconds is required when mode is 'periodic' or 'both'")
        if self.mode in ("periodic", "both") and self.get_inputs_fn is None:
            raise ValueError("get_inputs_fn is required when mode is 'periodic' or 'both'")


class BaseA2AAgent:
    """
    Abstract base class for AgentVault A2A agents.

    Developers should inherit from this class and implement the required
    `handle_...` methods to define the agent's behavior in response to
    A2A protocol requests (tasks/send, tasks/get, tasks/cancel, tasks/sendSubscribe).

    The `agentvault_server_sdk.fastapi_integration` module provides helpers
    to expose subclasses of `BaseA2AAgent` via a FastAPI router.
    """

    def __init__(self, agent_metadata: Optional[Dict[str, Any]] = None):
        """
        Initializes the base agent.

        Args:
            agent_metadata: Optional dictionary containing metadata specific
                            to this agent instance (e.g., configuration, loaded models).
        """
        self.agent_metadata = agent_metadata or {}
        logger.info(f"Initialized BaseA2AAgent: {self.__class__.__name__}")

    async def handle_task_send(self, task_id: Optional[str], message: Message) -> str:
        """
        Handle an incoming message for a task (initiation or continuation).

        This method is called when the A2A endpoint receives a 'tasks/send' request.
        Implementations should process the message, potentially update internal
        task state, start background work, and return the task ID.

        Args:
            task_id: The ID of the task if it's an existing task, None if initiating.
            message: The message received from the client.

        Returns:
            The unique ID of the task (either existing or newly created).

        Raises:
            NotImplementedError: This method must be implemented by subclasses.
            A2AError (or subclass): Can be raised for specific processing errors
                                   (e.g., invalid input, task failure).
        """
        raise NotImplementedError("Subclasses must implement handle_task_send")

    async def handle_task_get(self, task_id: str) -> Task:
        """
        Handle a request to retrieve the current state of a task.

        This method is called when the A2A endpoint receives a 'tasks/get' request.
        Implementations should fetch the current status, message history, and
        artifacts for the specified task ID and return them as a Task object.

        Args:
            task_id: The ID of the task to retrieve.

        Returns:
            A Task object representing the current state of the task.

        Raises:
            NotImplementedError: This method must be implemented by subclasses.
            A2AError (or subclass): Can be raised if the task is not found or
                                   an error occurs during retrieval.
        """
        raise NotImplementedError("Subclasses must implement handle_task_get")

    async def handle_task_cancel(self, task_id: str) -> bool:
        """
        Handle a request to cancel an ongoing task.

        This method is called when the A2A endpoint receives a 'tasks/cancel' request.
        Implementations should attempt to stop the processing for the specified
        task ID and update its state to CANCELED.

        Args:
            task_id: The ID of the task to cancel.

        Returns:
            True if the cancellation request was accepted (even if cancellation
            is asynchronous), False otherwise.

        Raises:
            NotImplementedError: This method must be implemented by subclasses.
            A2AError (or subclass): Can be raised if the task cannot be canceled
                                   (e.g., already completed, not found).
        """
        raise NotImplementedError("Subclasses must implement handle_task_cancel")

    async def handle_subscribe_request(self, task_id: str) -> AsyncGenerator[A2AEvent, None]:
        """
        Handle a request to subscribe to Server-Sent Events (SSE) for a task.

        This method is called when the A2A endpoint receives a 'tasks/sendSubscribe'
        request. Implementations should return an async generator that yields
        A2AEvent objects (TaskStatusUpdateEvent, TaskMessageEvent,
        TaskArtifactUpdateEvent) as they occur for the specified task ID.

        The generator should typically run indefinitely until the task reaches a
        terminal state or the client disconnects. The framework handles formatting
        these events into the SSE protocol.

        Args:
            task_id: The ID of the task to subscribe to.

        Yields:
            A2AEvent: Events related to the task's progress.

        Raises:
            NotImplementedError: This method must be implemented by subclasses.
            A2AError (or subclass): Can be raised if the task is not found or
                                   subscription is not possible.
        """
        raise NotImplementedError("Subclasses must implement handle_subscribe_request")
        # Required to make it an async generator type hint-wise, even if never reached
        if False: # pragma: no cover
            yield # pragma: no cover

    def get_attestation_schedule(self) -> Optional[List[AttestationScheduleEntry]]:
        """
        Return the ZKP attestation schedule for this agent.

        Override this method to enable automatic self-attestation. The SDK
        integration layer reads this at startup and wires up the corresponding
        ZKPAttestationClient triggers.

        Returns:
            None (default): attestation is disabled for this agent.
            List[AttestationScheduleEntry]: one entry per circuit to attest against.

        Example::

            def get_attestation_schedule(self):
                return [
                    AttestationScheduleEntry(
                        circuit_id="fairMarkupPolicy/v1.0.0",
                        mode="both",                   # event_driven + periodic
                        interval_seconds=3600,         # from registry policy
                        get_inputs_fn=self._get_markup_inputs,
                        event_types=["TokenTransferCompleted"],
                    )
                ]
        """
        return None


# Ensure the logger is configured if this module is run standalone (e.g., for testing)
if __name__ == "__main__":
     logging.basicConfig(level=logging.INFO)
     logger.info("BaseA2AAgent class defined.")
