"""Exception hierarchy for TheProtocol SDK."""

from typing import Optional, Any


class ProtocolError(Exception):
    """Base exception for all TheProtocol SDK errors."""
    pass


class A2AError(ProtocolError):
    """Base exception for A2A protocol errors."""
    pass


class A2AConnectionError(A2AError):
    """Connection failed to remote agent."""
    pass


class A2ATimeoutError(A2AConnectionError):
    """Request to remote agent timed out."""
    pass


class A2AAuthenticationError(A2AError):
    """Authentication failed (missing key, bad OAuth, etc.)."""
    pass


class A2ARemoteAgentError(A2AError):
    """Remote agent returned an error response."""

    def __init__(self, message: str, status_code: Optional[int] = None, response_body: Optional[Any] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.status_code is not None:
            parts.append(f"status={self.status_code}")
        return " | ".join(parts)


class A2AMessageError(A2AError):
    """Invalid message format or content."""
    pass


class KeyManagementError(ProtocolError):
    """Credential resolution failed."""
    pass


class AgentServerError(ProtocolError):
    """Error in agent server implementation."""
    pass


class TaskNotFoundError(AgentServerError):
    """Task ID does not exist."""

    def __init__(self, task_id: str, message: str = "Task not found"):
        self.task_id = task_id
        super().__init__(f"{message}: {task_id}")


class InvalidStateTransitionError(AgentServerError):
    """Invalid task state transition attempted."""

    def __init__(self, task_id: str, from_state: str, to_state: str):
        self.task_id = task_id
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"Task '{task_id}': cannot transition from {from_state} to {to_state}")
