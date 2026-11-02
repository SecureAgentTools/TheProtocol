"""
Custom exception classes for the AgentVault Server SDK.
"""

class AgentServerError(Exception):
    """Base exception for errors originating within an AgentVault agent implementation.

    caller_safe: the message is meant for the agent's caller and goes to it whole (V0653 (am) item 2,
    caller_errors.caller_message); anything else reaches the caller as a generic message with an error id, and the
    agent's log gets the whole exception. Set it on a subclass, or on an instance, to pass a message through.
    """
    caller_safe = False

class TaskNotFoundError(AgentServerError):
    """Raised when an operation is attempted on a non-existent task ID."""
    caller_safe = True

    def __init__(self, task_id: str, message: str = "Task not found"):
        self.task_id = task_id
        super().__init__(f"{message}: {task_id}")

class InvalidStateTransitionError(AgentServerError):
    """Raised when an invalid state transition is attempted for a task."""
    caller_safe = True

    def __init__(self, task_id: str, from_state: str, to_state: str, message: str = "Invalid state transition"):
        self.task_id = task_id
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"{message} for task '{task_id}': Cannot transition from {from_state} to {to_state}")

class AgentProcessingError(AgentServerError):
    """Raised for general errors during the agent's core task processing logic."""
    pass

class ConfigurationError(AgentServerError):
    """Raised when there is an issue with the agent's configuration."""
    pass

# Add more specific exceptions as needed, inheriting from AgentServerError or more specific types.
